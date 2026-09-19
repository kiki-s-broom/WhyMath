"""L3 생성 파이프라인 — 라우팅 → 캐시 → 생성 → 관측 결선 (M1.2-live S1·S4).

라우터(순수 결정)와 외부 의존(LLMProvider·CacheBackend·TraceSink·AsyncJobQueue)을
*조립*하는 얇은 오케스트레이션 계층이다. 결정 로직은 일절 바꾸지 않고 Router.route()에
위임한다.

흐름 (03a §F.1 캐시 키·§F.2 Langfuse 필드·§D.3 QUALITY 비동기):
  1. Router().route(req) → decision
  2. decision.mode == "async"(QUALITY) → 동기 호출 금지(03a §D.3):
       - queue 미주입 → QualityQueueUnavailableError(미구성 시 안전 폴백, API가 503).
       - queue 주입 → JSON payload enqueue → job_id 반환(GenerationResult.status="queued").
         enqueue 자체 실패(broker 다운)도 QualityQueueUnavailableError로 변환(503).
       - 어느 경우든 provider를 동기 호출하지 않는다. enqueue도 Langfuse에 기록한다.
  3. 그 외(sync) → cache_key_for()로 조회: HIT면 trace+반환, MISS면 provider 생성→cache
     저장→trace+반환

경계 메모 (CLAUDE.md 절대 금기): 반환 텍스트는 *검증 전 원시 모델 출력*이다. 03 문서
환각 방어 파이프라인을 통과하기 전에는 학생에게 직접 노출 금지 ("LLM 응답을 검증
없이 학생에게 제공 금지"). 비동기 경로는 텍스트를 *즉시 돌려주지 않고* job_id만 주며,
폴링으로 받은 결과 역시 동일하게 검증 전 출력이다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from whymath_backend.config import get_settings
from whymath_backend.l3.interfaces import (
    AsyncJobQueue,
    CacheBackend,
    LLMProvider,
    TraceSink,
)
from whymath_backend.l3.models import (
    CostTier,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    RoutingRequest,
    Usage,
)
from whymath_backend.l3.pregenerate.validator import SeedValidator, validate_response
from whymath_backend.l3.router import (
    Router,
    _as_cost_tier,
    actual_cost_krw,
    cache_key_for,
    langfuse_fields,
)


class QualityQueueUnavailableError(RuntimeError):
    """QUALITY(27b) 비동기 큐를 쓸 수 없음 — 미구성 또는 broker 도달 실패 (03a §D.3).

    QUALITY는 p50≈14초·병렬 미작동이라 동기 호출이 *절대* 금지된다(GPU 단일 점유).
    라우터가 mode='async'로 결정한 요청에 대해 (a) 큐가 주입되지 않았거나(미구성)
    (b) enqueue가 broker 도달 실패로 던지면, 동기 폴백 대신 이 예외를 던진다 —
    호출자(엔드포인트)는 이를 명확한 503으로 변환하며 500 스택트레이스를 노출하지
    않는다(가용성 우선: 503 '잠시 후 재시도'가 500 '내부 오류'보다 정직·안전).
    """


@dataclass(slots=True, frozen=True)
class GenerationResult:
    """파이프라인 결과 — 라우팅 메타데이터 + (동기) 생성 텍스트 또는 (비동기) job_id.

    ⚠️ 이름 구분: `l3.models.GenerationResult`(provider 경계의 생성 1회 결과 — text+usage)
    와 이름만 같고 **다른 타입**이다. 이 타입은 파이프라인 *오케스트레이션* 결과다 —
    파이프라인이 provider의 models.GenerationResult에서 `.text`를 소비하고 `.usage`는
    trace(실측 cost_krw·토큰·지연)로 흘린 뒤, 이 타입으로 상위에 돌려준다.

    호출자/엔드포인트가 라우팅 결정(어느 티어·패밀리·모드)과 캐시 적중 여부를
    응답에 노출할 수 있도록 decision을 함께 돌려준다.

    두 모드를 하나의 타입으로 표현한다(분기 단순화):
      - 동기(sync) 완료: status="completed", text=생성물, cache_hit=불린, job_id=None.
      - 비동기(async) 큐잉: status="queued", text="", cache_hit=False, job_id=큐 작업 ID.
        텍스트는 *즉시 없다* — 호출자는 job_id로 폴링한다(03a §D.3). 빈 text는 "아직
        없음"을 뜻하며, 학생 노출 대상이 아니다.

    `text`(있을 때)는 *검증 전 원시 출력*이다(모듈 docstring 경계 메모 참조).

    `validation_signal`은 런타임 shadow 검증(slice 40) 결과를 *호출자에게 노출*한다 —
    None=통과 또는 미검증(validator 미주입·캐시 히트·비동기), 문자열=환각 사유(거짓 수치
    관계 등). trace 기록과 *같은 값*이지만, fire-and-forget 관측 싱크와 달리 호출자
    (엔드포인트·상위 계층)가 *프로그램적으로* 읽어 후속 결정(플래그·재생성·L4/L5 라우팅)에
    쓸 수 있다. **비차단**: 신호가 있어도 text·cache_hit·status는 영향받지 않는다.
    """

    decision: RoutingDecision
    text: str
    cache_hit: bool
    # 비동기(QUALITY) 큐잉 시에만 채워지는 작업 ID. 동기 경로는 None.
    job_id: str | None = None
    # "completed"(동기 완료) / "queued"(비동기 큐 적재). 엔드포인트가 202 vs 200 분기에 사용.
    status: str = "completed"
    # 런타임 shadow 검증 환각 신호(비차단·관측). None=통과/미검증, 문자열=사유.
    validation_signal: str | None = None

    @property
    def is_queued(self) -> bool:
        """비동기 큐에 적재돼 job_id 폴링이 필요한 결과인가."""
        return self.status == "queued"


def _build_async_payload(
    prompt: str,
    system: str,
    decision: RoutingDecision,
    *,
    training_allowed: bool | None = None,
) -> dict[str, object]:
    """비동기 큐 payload(JSON-safe dict) 구성 — 워커 태스크 스키마와 일치.

    RoutingDecision은 use_enum_values=True라 enum이 문자열로 나오고, `mode="json"`이
    나머지 타입까지 JSON 네이티브로 낮춘다 — Celery 전송에 안전하다(pickle 미사용).
    워커는 이 dict에서 RoutingDecision을 다시 검증·재구성한다(queue/tasks.py PAYLOAD_* 키와 동일).

    **`mode="json"`을 명시하는 이유**(ARCH-49 실측): 기본 `model_dump()`는 파이썬 타입을
    그대로 남긴다 — `tuple` 필드는 tuple로 나오고, `json.dumps`를 거치면 list가 되어
    **왕복이 동치가 아니게 된다**. 직렬화 자체는 성공하므로 이 결함은 조용하다: 큐에 넣기
    전 payload와 워커가 받은 payload를 비교하는 쪽에서만 드러난다. `data_licenses`
    (tuple) 추가가 그 상태를 실제로 만들었고 `test_enqueued_payload_is_json_safe_and_complete`
    가 잡았다. 여기서 JSON 네이티브로 낮추면 앞으로 어떤 비-JSON 타입 필드가 늘어도
    같은 함정을 다시 밟지 않는다(docstring이 약속하는 "JSON-safe"가 실제로 참이 된다).

    `training_allowed`는 AI 학습/개선에 데이터 사용 동의 여부(EOS §48)로, enqueue
    시점과 워커 생성 완료 시점 모두 Langfuse trace 메타데이터로 남긴다.
    """
    return {
        "prompt": prompt,
        "system": system,
        "decision": decision.model_dump(mode="json"),
        "training_allowed": training_allowed,
    }


def _image_digest(images: Sequence[str] | None) -> str | None:
    """멀티모달 입력 이미지 목록의 안정적 다이제스트(SHA256) — 캐시 키 식별용(순수).

    None/빈 목록이면 None(텍스트 호출 → 캐시 키 불변). 순서 포함 결합 후 해시하므로 같은
    이미지 집합은 같은 다이제스트(같은 크롭 재인식은 캐시 적중)·다른 이미지는 다른 키.
    """
    if not images:
        return None
    joined = "\x1e".join(images)  # RS(레코드 구분자)로 결합 — base64에 없는 바이트
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _apply_family_preference(
    decision: RoutingDecision, prefer_local_family: ModelFamily | None
) -> RoutingDecision:
    """LOCAL FAST/MID 결정의 **패밀리 축만** 호출부 선호로 갈아탄다 — 비용·크기·모드는 불변.

    라우터의 축3(MATH/GENERAL)은 task_type·call_site로 결정되는데, 같은 task_type을 쓰면서도
    *그 호출만* 일반 instruct 모델이 적합한 자리가 있다(프로즈 문맥화·동등문제 저작 — 수학 추론이
    아니라 instruction-following). 그 자리들이 지금까지 라우터 밖에서 `RoutingDecision`을 손수
    재조립해 왔고(`wh1_prose._decide_routing`·`l3/equivalent/rephrase._decide_routing` — 같은
    코드의 3대째 미러), 그 재조립이 곧 파이프라인 우회의 원인이었다(관측·캐시 미결선). 여기로
    끌어올려 **라우터 경유를 유지한 채** 같은 선호를 표현한다.

    적용 조건은 종전 미러와 동일하다: ① LOCAL 결정일 것 ② 크기가 FAST 또는 MID일 것(QUALITY는
    비동기 전용이라 손대지 않는다) ③ 이미 선호 패밀리면 그대로. 어느 하나라도 어긋나면 라우터
    결정을 **그대로** 돌려준다(불변식 4 — 라우터의 비용·크기·모드 결정은 존중).

    데이터 등급 게이트의 판정·발동 신호(`data_export_blocked`·`data_export_reason`)는 **승계**
    한다 — 패밀리 축만 갈아탈 뿐 법적 판정을 다시 하지 않는다(EOS-59 ②: 안 실으면 발동 사실이
    관측에서 사라진다).
    """
    if prefer_local_family is None:
        return decision
    if decision.cost_tier != CostTier.LOCAL.value:
        return decision
    if decision.local_model not in (LocalModelTier.FAST.value, LocalModelTier.MID.value):
        return decision
    if decision.local_family == prefer_local_family.value:
        return decision
    return RoutingDecision(
        cost_tier=decision.cost_tier,
        local_family=prefer_local_family,
        local_model=decision.local_model,
        mode=decision.mode,
        reason=f"{decision.reason} \u2192 prefer:{prefer_local_family.value}",
        est_latency_ms=decision.est_latency_ms,
        est_cost_krw=decision.est_cost_krw,
        data_export_blocked=decision.data_export_blocked,
        data_export_reason=decision.data_export_reason,
    )


async def generate(
    req: RoutingRequest,
    prompt: str,
    system: str,
    *,
    provider: LLMProvider,
    cache: CacheBackend,
    trace: TraceSink,
    queue: AsyncJobQueue | None = None,
    cache_ttl_s: int | None = None,
    student_id_hash: str | None = None,
    validator: SeedValidator | None = None,
    skip_cache_on_signal: bool = False,
    images: Sequence[str] | None = None,
    training_allowed: bool | None = None,
    prefer_local_family: ModelFamily | None = None,
    temperature: float | None = None,
) -> GenerationResult:
    """라우팅 → (비동기면 큐잉 / 동기면 캐시·생성) → 관측을 조립한다.

    Args:
        req: 라우팅 입력 신호.
        prompt: 사용자 프롬프트(검증 전 원시 입력).
        system: 시스템 프롬프트.
        provider: LLM 생성 백엔드(LOCAL이면 OllamaProvider).
        cache: 응답 캐시(S1은 인메모리 스텁).
        trace: 관측성 싱크(S1은 RecordingTraceSink).
        queue: QUALITY(27b) 비동기 작업 큐(S4 CeleryJobQueue). None이면 비동기 결정 시
            QualityQueueUnavailableError(미구성 폴백 → API 503).
        cache_ttl_s: 캐시 TTL(초). None이면 Settings.cache_ttl_s.
        student_id_hash: Langfuse 기록용 학생 ID 해시(직접 ID 금지, 03a §F.2).
        training_allowed: AI 모델 학습/개선에 데이터 사용 동의 여부(EOS §48). 관측용.
        prefer_local_family: LOCAL FAST/MID 결정일 때만 **패밀리 축**을 이 값으로 갈아탄다
            (`_apply_family_preference`). None(기본)이면 라우터 결정 그대로 — 기존 호출부는
            비트동일. 비용·크기·모드는 어느 경우에도 라우터 것을 존중한다(불변식 4).
        temperature: 샘플링 온도(선택). None(기본)이면 제공자 기본 온도 — 즉 **기존 동작
            무변경**. ⚠️ 캐시 키는 `(prompt, system, 3축)`이라 **온도를 포함하지 않는다** —
            같은 프롬프트를 다른 온도로 부르면 앞선 결과가 적중한다. 온도를 다양성 확보
            수단으로 쓰는 호출부는 프롬프트 자체에 회차 축(턴 번호 등)이 들어가 키가 갈리는지
            확인하고 쓴다(wh1_prose는 턴 번호·행위 유형·판정이 프롬프트에 있어 갈린다).
        validator: 런타임 shadow 검증기(L3 결정론 도구, 예: `default_seed_validator()`).
            주입 시 *캐시 미스로 새로 생성된 출력*에만 적용해 거짓 수치 관계 등 환각
            신호를 trace의 `validation_signal`로 기록한다. **비차단** — 반환 텍스트·
            캐시 저장에 영향을 주지 않는다(학생 노출 차단은 L4/L5 책임, CLAUDE.md). None
            (기본)이면 검증을 돌리지 않아 오버헤드 0(opt-in). 캐시 히트·비동기 경로는
            shadow 검증 대상이 아니다(미스 생성물만 — 히트는 적재 시 이미 검증·중복 회피).
        skip_cache_on_signal: True면 shadow 검증이 *환각 신호를 낸 미스 생성물*을 캐시에
            적재하지 않는다(증명된 거짓 콘텐츠를 캐시에 *남기지 않음* — 캐시 위생). 신호가
            없으면(통과·미검증) 정상 적재. `validator`가 없으면 신호 자체가 없어 무효과.
            **반환 텍스트·신호는 불변** — 호출자엔 여전히 원시 출력+신호가 가고, *캐시*
            만 건너뛴다(다음 동일 요청은 재생성). 기본 False(기존 동작·항상 적재). False
            positive 시 비용(재생성)만 들고 정확성은 안전 — *결정론 검증 한정* 권장.

    Returns:
        GenerationResult — 동기면 텍스트(status="completed"), 비동기면 job_id(status="queued").

    Raises:
        QualityQueueUnavailableError: 큐 미주입(미구성)이거나 enqueue 실패(broker 다운).
    """
    decision = _apply_family_preference(Router().route(req), prefer_local_family)

    # QUALITY(27b)는 동기 호출 불가(p50≈14초·GPU 단일 점유, 03a §D.3) → 비동기 큐 경로.
    if decision.mode == "async":
        if queue is None:
            # 큐 미구성 → 안전 폴백(동기 호출은 절대 금지). API가 503으로 변환.
            raise QualityQueueUnavailableError(
                "QUALITY(27b) 동기 호출 불가 — 비동기 큐가 구성되지 않았습니다(03a §D.3). "
                f"결정: cost_tier={decision.cost_tier}, local_model={decision.local_model}."
            )
        payload = _build_async_payload(prompt, system, decision, training_allowed=training_allowed)
        try:
            job_id = await queue.enqueue(payload)
        except Exception as exc:  # noqa: BLE001 — broker 다운 등 디스패치 실패를 도메인 예외로
            # broker 도달 실패는 가용성 문제 → 명확한 도메인 예외로 변환(API 503, 500 금지).
            raise QualityQueueUnavailableError(
                "QUALITY(27b) 작업 큐 디스패치 실패 — broker 도달 불가일 수 있습니다(03a §D.3). "
                f"원인: {type(exc).__name__}: {exc}"
            ) from exc
        # enqueue도 관측 기록한다(mode=async — SLA 평가에서 동기와 분리, 03a §F.2).
        # provider는 호출하지 않는다(QUALITY 동기 금지). 캐시도 타지 않는다(결과 미존재).
        # 실측 비용: enqueue 시점엔 생성이 없어 0.0(로컬 QUALITY 27b=0원 확정 — 토큰·지연
        # 실측은 워커가 자기 trace로 기록한다, queue/tasks.py). usage는 미존재라 None.
        trace.record(
            langfuse_fields(
                decision,
                cache_hit=False,
                student_id_hash=student_id_hash,
                cost_krw=0.0,
                training_allowed=training_allowed,
            )
        )
        return GenerationResult(
            decision=decision, text="", cache_hit=False, job_id=job_id, status="queued"
        )

    ttl = cache_ttl_s if cache_ttl_s is not None else get_settings().cache_ttl_s
    # 멀티모달 입력 이미지는 캐시 키에 다이제스트로 반영(같은 프롬프트라도 이미지 다르면 다른 캐시).
    # images=None(텍스트 호출)이면 image_digest=None → 캐시 키가 기존과 100% 동일(하위호환).
    key = cache_key_for(prompt, system, decision, image_digest=_image_digest(images))

    cached = await cache.get(key)
    if cached is not None:
        # 캐시 적중도 반드시 기록(분포·KPI 왜곡 방지, 03a §F.1).
        # 실측 비용: 적중=신규 LLM 호출 없음=0원 *확정*(cost_krw=0.0). 토큰·지연 usage는
        # 이 요청에서 실측된 게 없어 None(적재 시점 실측은 미스 기록에 이미 남았다).
        trace.record(
            langfuse_fields(
                decision,
                cache_hit=True,
                student_id_hash=student_id_hash,
                cost_krw=0.0,
                # 2층 캐시의 (2) — 프롬프트-해시 적중. 경로는 자기 cache_hit에서 유도한다
                # (상위가 주입할 필요 없음·03c §4).
                content_source="prompt_cache",
                training_allowed=training_allowed,
            )
        )
        return GenerationResult(decision=decision, text=cached, cache_hit=True)

    # 캐시 미스 → 실제 생성(검증 전 원시 출력) → (shadow 검증) → 조건부 캐시 저장 → 기록.
    # images는 *있을 때만* 전달한다 — 텍스트 전용 제공자(기존 구현·테스트 가짜)는 images
    # 인자가 없어도 그대로 동작(하위호환). 멀티모달 호출만 images-수신 제공자를 쓴다.
    # provider 반환은 models.GenerationResult(text, usage) — text는 종전 str 경로 그대로
    # 소비하고, usage(실측 토큰·지연)는 trace로 흘린다(S1 게이트 ② 배선).
    # images·temperature는 *있을 때만* 전달한다 — 인자를 받지 않는 기존 제공자·테스트 가짜가
    # 그대로 동작하도록(하위호환). None을 명시 전달하면 그 가짜들이 TypeError로 죽는다.
    if images is not None and temperature is not None:
        generated = await provider.generate(
            prompt, system, decision, images=images, temperature=temperature
        )
    elif images is not None:
        generated = await provider.generate(prompt, system, decision, images=images)
    elif temperature is not None:
        generated = await provider.generate(prompt, system, decision, temperature=temperature)
    else:
        generated = await provider.generate(prompt, system, decision)
    output = generated.text
    usage: Usage | None = generated.usage
    # 실측 비용(원) — 로컬=0.0 확정 / 클라우드=토큰 산정. usage 자체가 없거나(미계측 제공자)
    # 클라우드인데 토큰이 미상이면 None으로 남긴다('미상'과 '0원'을 구분 — 지어내지 않음).
    actual_krw: float | None
    is_cloud = _as_cost_tier(decision.cost_tier) is not CostTier.LOCAL
    if usage is None:
        actual_krw = None
    elif is_cloud and (usage.input_tokens is None or usage.output_tokens is None):
        actual_krw = None
    else:
        actual_krw = actual_cost_krw(decision, usage)
    # 런타임 shadow 검증(비차단·opt-in) — 거짓 수치 관계 등 환각 신호를 관측에 남긴다.
    # 캐시 적재 *전에* 검증해야 skip_cache_on_signal이 적재 여부를 결정할 수 있다.
    signal = validate_response(validator, output) if validator is not None else None
    # 신호는 구조화 `ValidationSignal`(slice 59) — 문자열 경계(trace·GenerationResult)에는
    # `.reason`을 흘린다(형식 불변·str 계약 유지). 캐시 위생 판정은 신호 *유무*(bool)만 본다.
    reason = signal.reason if signal is not None else None
    # 캐시 위생: 신호 난 출력은 skip_cache_on_signal=True면 *적재하지 않는다*(증명된 거짓을
    # 캐시에 남기지 않음). 반환 텍스트·신호는 불변 — 캐시만 건너뛴다(다음 요청은 재생성).
    if not (skip_cache_on_signal and signal is not None):
        await cache.set(key, output, ttl)
    trace.record(
        langfuse_fields(
            decision,
            cache_hit=False,
            student_id_hash=student_id_hash,
            validation_signal=reason,
            # 실측(S1 게이트 ②) — provider가 포착한 usage + 토큰 산정 비용(est_*와 분리).
            usage=usage,
            cost_krw=actual_krw,
            content_source="generate",  # 2층 캐시의 (3) — 실제 LLM 생성.
            training_allowed=training_allowed,
        )
    )
    return GenerationResult(
        decision=decision, text=output, cache_hit=False, validation_signal=reason
    )
