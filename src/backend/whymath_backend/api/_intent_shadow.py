"""학생 의도 *섀도 관측* — laya-ko-whymath 판단을 규칙 분류기 옆에 로그로만 남긴다 (PED-48).

**왜 있나**: 학생 턴의 `student_intent`는 결정론 토큰 규칙(`l4/turn_meta.classify_student_intent`)이
정한다. 2026-10-27 합성 시험 272문장 비교에서 그 규칙은 답 요구 메시지의 14%만 `포기`로 잡았고
전체의 71%가 잔여 범주 `이해확인`으로 수렴했다(합성 데이터·`has_solution=False` 고정 조건 — 실서비스
분포는 다를 수 있다). 같은 문장에서 한국어 파인튜닝 분류기 laya-ko-whymath v1은 6종 의도 0.893을
냈다. 교체 여부는 **실학생 트래픽에서 두 분류기를 나란히 재 본 뒤** 정한다(Kiki 결정 2026-10-27 —
"측정 없는 도입 없음"). 이 모듈이 그 측정의 수집 장치다.

**불변식** (`l4/misconception/shadow.py`·`l4/step_shadow.py` 선례 계승):
- **비노출**: 공개 함수는 `None`을 돌려준다. 호출자(coach)가 결과를 받을 변수가 없어 학생 응답·
  DB 적재·교수 결정에 Laya 판단이 들어갈 경로가 구조적으로 없다.
- **비차단**: 판정은 학생 턴 커밋 *뒤* `_spawn`(create_task)으로 띄우고 즉시 반환한다. 판정
  코루틴은 모든 예외를 흡수한다. 동시 판정 수는 `MAX_IN_FLIGHT`로 막는다 — 몰릴 때 laya(CPU)가
  같은 머신의 튜터 LLM을 굶기지 않게, 넘치면 호출하지 않고 `Overloaded` 레코드만 남긴다.
- **침묵 실패 금지**: 흡수한 예외는 *예외 타입명*과 HTTP 상태 코드를 로그·레코드에 남긴다. 실패·
  건너뜀도 레코드 1건으로 남겨 "작동한 비율"을 잴 수 있게 한다(성공만 기록하면 실패율이 0으로 위장).
- **프라이버시**: 학생 원문·원문 해시·세션/학생 식별자를 레코드와 로그에 넣지 않는다(미성년자
  채팅 평문 저장 금지). 관측 시각은 *시 단위로 절삭*한다 — 마이크로초 시각은 `dialogue_turn`
  시각과 조인돼 레코드를 특정 학생에게 다시 묶을 수 있다. 원문은 메모리에서 *내부망* laya-serve로만
  전송된다: URL은 설정 검증이 내부망 호스트만 허용하고(`config.py`), 클라이언트는
  `trust_env=False`로 환경 프록시(HTTP_PROXY·Windows 시스템 프록시)를 *무시*한다 — 프록시
  경유는 내부망 전송 약속을 깬다.
- **보조 신호**: 개인정보 확률은 관측값일 뿐 PII 보호 절차를 대체하지 않는다(법령 유래 절차의
  기계 대체 금지). 이 레코드를 근거로 무언가를 자동으로 가리거나 차단하지 않는다.

**측정 범위**: 발화가 빈 턴(풀이만 제출 — 규칙 분류 `답시도`)은 판정할 문장이 없어 관측하지 않는다.
비교는 *발화가 있는 학생 턴*에 한정된다.

**레코드 수집**: 레코드는 `whymath.api.intent_shadow.record` 로거로 나간다. 기본 로깅 설정에는
이 로거의 핸들러가 없어 레코드가 버려지므로, 서버를 `scripts/demo/wh1_shadow_logconfig.json`으로
띄워 `intent_shadow_records.log`에 받는다(절차 = `docs/architecture/shadow_measurement_runbook.md`).

**레이어**: laya-serve는 HTTP 외부 프로세스라 L4(순수 계층)에 둘 수 없다. 서빙 계층(`api`)의
비공개 모듈로 두고, L4의 규칙 분류기 결과는 *값*으로만 받는다.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from whymath_backend.config import Settings, get_settings
from whymath_backend.l4.misconception.shadow import _spawn
from whymath_backend.schema.enums import StudentIntent

logger = logging.getLogger("whymath.api.intent_shadow")
# 구조화 레코드 JSON 한 줄 — 평문 로그와 분리된 자식 로거(step_shadow.record 동형).
record_logger = logging.getLogger("whymath.api.intent_shadow.record")

# 레코드 형식 버전 — 필드가 바뀌면 올린다(수집기가 버전별로 읽을 수 있게 · R6-03).
RECORD_SCHEMA_VERSION = 1

# laya-ko-whymath v1이 학습한 질문지와 *글자 하나까지* 같아야 한다 — 질문 문구가 바뀌면 모델이
# 학습 때와 다른 입력을 보게 되어 정확도 근거(0.893)가 성립하지 않는다. 바꾸려면 재학습과 함께
# QUESTIONS_VERSION을 올린다.
QUESTIONS_VERSION = "questions_v1"
LAYA_QUESTIONS: dict[str, object] = {
    "intent": {
        "type": "choice",
        "instructions": (
            "A student sent this message to an AI math tutor. "
            "What does the student want from the tutor right now?"
        ),
        "criteria": {
            "concept": "understand a concept",
            "stuck": "stuck at a step",
            "answer_only": "only the answer",
            "hint": "a hint",
            "check": "check my answer",
            "chitchat": "not about math",
        },
    },
    "pii": {
        "type": "noul",
        "instructions": (
            "Does the message reveal personal information such as a person's name, "
            "school name (e.g. ○○중, ○○고), phone number (010-), address, email or SNS ID? "
            "Grade or age alone is not personal information."
        ),
    },
}

LayaIntent = Literal["concept", "stuck", "answer_only", "hint", "check", "chitchat"]
ShadowRoute = Literal["create_session", "append_turns"]

# 학습한 체크포인트를 laya-serve가 `multilingual` 이름으로 등록해 서빙한다(LAYA_EXTRA_MODELS).
# 명시하지 않으면 영어처럼 보이는 짧은 발화가 원본 영어 체크포인트로 라우팅될 수 있다.
_LAYA_MODEL = "multilingual"

# 동시 판정 상한 — laya-serve는 CPU에서 건당 0.3~0.5초이고 Phaiakes9에서 튜터 LLM과 CPU를
# 나눠 쓴다. 넘치면 호출하지 않고 `Overloaded`로 기록한다(건너뜀도 분모에 남게).
MAX_IN_FLIGHT = 4
_in_flight = 0

# 넘침으로 건너뛴 턴의 실패 이름 — 예외 타입명이 아니라 이 모듈이 정한 사유 코드다.
OVERLOADED = "Overloaded"


class _IntentAnswer(BaseModel):
    """laya-serve choice 답 1건 — 경계 검사용 최소 스키마(나머지 필드는 무시)."""

    model_config = ConfigDict(extra="ignore")

    choice: LayaIntent
    answer_confidence: float = Field(ge=0.0, le=1.0)


class _PiiAnswer(BaseModel):
    """laya-serve noul 답 1건 — P(true)."""

    model_config = ConfigDict(extra="ignore")

    noul: float = Field(ge=0.0, le=1.0)


class _Answers(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: _IntentAnswer
    pii: _PiiAnswer


class _Routing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str


class _LayaResponse(BaseModel):
    """`POST /v1/systemone` 응답의 경계 스키마 — 검사를 못 넘은 응답은 레코드에 싣지 않는다.

    실물 laya-serve 0.4.15 응답(`tests/backend/api/fixtures/laya_systemone_responses.json`)으로
    파싱을 검증한다 — 손으로 쓴 가짜 응답만으로 외부 표면 정합을 선언하지 않는다.
    """

    model_config = ConfigDict(extra="ignore")

    answers: _Answers
    routing: _Routing


def _observed_hour() -> datetime:
    """관측 시각을 *시 단위*로 절삭 — 턴 시각과의 조인으로 학생을 특정하지 못하게 한다."""
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


class IntentShadowObservation(BaseModel):
    """의도 섀도 관측 1건 — record_logger로 JSON 한 줄 emit.

    **담지 않는 것**: 학생 원문·원문 해시·dialogue/student/session 식별자·정밀 시각. 일치도 측정에는
    두 분류기의 라벨 쌍만 필요하고, 식별자나 정밀 시각이 있으면 레코드가 학생 대화와 다시 결합된다.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = RECORD_SCHEMA_VERSION
    route: ShadowRoute
    """어느 엔드포인트의 학생 턴인지 — 세션 첫 턴과 이후 턴의 분포가 다를 수 있어 나눠 본다."""

    rule_intent: StudentIntent | None
    """규칙 분류기 결과(DB에 실제로 적재된 값). 발화가 있는 턴만 관측하므로 실제로는 항상 값이
    있지만, `classify_student_intent`의 반환 타입(`| None`)을 그대로 받아 계약을 좁히지 않는다."""

    has_solution: bool
    """풀이 제출 동반 여부 — 규칙 분류기의 `답시도` 판정 입력이라 비교 해석에 필요하다."""

    laya_intent: LayaIntent | None = None
    laya_confidence: float | None = None
    pii_prob: float | None = None
    routed_model: str | None = None

    questions_version: str = QUESTIONS_VERSION
    latency_ms: float
    """laya 왕복 + 검사 시간(클라이언트 생성 비용 제외). 실패·건너뜀이어도 기록한다."""

    failure: str | None = None
    """실패 시 예외 타입명(`ConnectError`·`TimeoutError`·`HTTPStatusError`·`ValidationError` 등)
    또는 사유 코드(`Overloaded`)."""

    http_status: int | None = None
    """응답을 받았을 때의 HTTP 상태 — `HTTPStatusError` 하나로 401·503이 같은 글자로 보이지 않게."""

    observed_at: datetime = Field(default_factory=_observed_hour)
    """관측 시각(UTC, *시 단위 절삭*)."""


@lru_cache(maxsize=1)
def _shared_ssl_context() -> ssl.SSLContext:
    """SSL 컨텍스트 1회 생성 — 클라이언트마다 만들면 인증서 적재로 건당 ~10ms를 이벤트 루프에서
    동기로 쓴다(리뷰 실측). http URL에도 httpx가 컨텍스트를 만들기 때문에 공유본을 넘긴다."""
    return httpx.create_ssl_context()


# 테스트 주입 좌석 — 기본은 실제 httpx 클라이언트. 테스트는 `httpx.MockTransport`를 끼운
# 클라이언트 팩토리로 바꿔 라이브 서버 없이 성공·실패 경로를 전부 재현한다(wh1_shadow_probe 선례).
ClientFactory = Callable[[float], httpx.AsyncClient]


def _default_client_factory(timeout_s: float) -> httpx.AsyncClient:
    # trust_env=False — 환경 프록시를 무시한다. 켜 두면 HTTP_PROXY가 있는 호스트에서 루프백
    # 주소조차 프록시를 경유해 학생 발화와 Bearer 키가 평문으로 프록시에 간다(httpx 0.28 실측).
    return httpx.AsyncClient(timeout=timeout_s, trust_env=False, verify=_shared_ssl_context())


_client_factory: ClientFactory = _default_client_factory


def set_client_factory(factory: ClientFactory | None) -> None:
    """테스트용 — None이면 기본 팩토리로 되돌린다."""
    global _client_factory
    _client_factory = factory if factory is not None else _default_client_factory


def shadow_configured(settings: Settings) -> bool:
    """섀도가 실제로 호출할 조건 — 스위치 + URL + 키가 *모두* 있어야 한다.

    켜졌는데 URL·키가 비면 설정 검증이 부팅을 거부한다(`config.py`). 이 함수는 그 뒤의 이중
    안전판이다 — 검증을 우회해 만든 Settings에서도 키 없는 호출·URL 없는 호출을 하지 않는다.
    """
    return bool(
        settings.laya_intent_shadow_enabled
        and settings.laya_intent_shadow_url
        and settings.laya_intent_shadow_api_key.get_secret_value()
    )


def _emit(observation: IntentShadowObservation) -> None:
    """레코드 1건 기록 — 실패하면 평문 경고(타입명)만 남기고 삼킨다."""
    try:
        if observation.failure is not None:
            logger.warning(
                "의도 섀도 판정 실패(비노출): %s http_status=%s",
                observation.failure,
                observation.http_status,
            )
        record_logger.info(observation.model_dump_json())
    except Exception as exc:  # noqa: BLE001 — 기록 실패도 본류를 깨지 않는다
        logger.warning("의도 섀도 기록 실패: %s", type(exc).__name__)


def spawn_intent_shadow(
    *,
    student_input: str,
    rule_intent: StudentIntent | None,
    has_solution: bool,
    route: ShadowRoute,
) -> None:
    """학생 턴 1건의 섀도 판정을 *백그라운드로* 띄우고 즉시 반환한다. 반환 None(비노출).

    꺼져 있거나 발화가 비어 있으면 아무것도 하지 않는다. 동시 판정이 `MAX_IN_FLIGHT`에 차 있으면
    호출 없이 `Overloaded` 레코드만 남긴다. 이 함수 자체도 본류를 깨지 않는다.
    """
    global _in_flight
    coro: Coroutine[object, object, None] | None = None
    try:
        settings = get_settings()
        if not shadow_configured(settings) or not student_input.strip():
            return
        if _in_flight >= MAX_IN_FLIGHT:
            _emit(
                IntentShadowObservation(
                    route=route,
                    rule_intent=rule_intent,
                    has_solution=has_solution,
                    latency_ms=0.0,
                    failure=OVERLOADED,
                )
            )
            return
        coro = observe_intent_shadow(
            student_input=student_input,
            rule_intent=rule_intent,
            has_solution=has_solution,
            route=route,
            url=settings.laya_intent_shadow_url,
            api_key=settings.laya_intent_shadow_api_key.get_secret_value(),
            timeout_s=settings.laya_intent_shadow_timeout_s,
        )
        _in_flight += 1
        try:
            _spawn(coro)
        except BaseException:
            _in_flight -= 1  # task가 못 떴으면 자리를 돌려준다
            raise
    # 관측 방어선 — 섀도는 본류를 안 깬다(비차단 불변)
    except Exception as exc:  # noqa: BLE001
        if coro is not None:
            coro.close()  # 못 띄운 코루틴을 닫는다('never awaited' 경고 방지)
        logger.warning("의도 섀도 spawn 실패: %s", type(exc).__name__)


async def observe_intent_shadow(
    *,
    student_input: str,
    rule_intent: StudentIntent | None,
    has_solution: bool,
    route: ShadowRoute,
    url: str,
    api_key: str,
    timeout_s: float,
) -> None:
    """laya-serve에 1회 질의하고 성공·실패 모두 레코드 1건을 남긴다. 반환 None.

    `timeout_s`는 *총* 시간 상한이다 — httpx의 timeout은 연결·쓰기·읽기 단계별이라 조금씩
    흘려 보내는 서버에선 합계가 상한을 넘으므로 `asyncio.timeout`으로 전체를 감싼다.
    never-break: HTTP·파싱·경계 검사·직렬화·로깅 전부를 흡수한다. `spawn_intent_shadow`가 잡은
    동시 판정 자리는 여기서 반드시 돌려준다(finally).
    """
    global _in_flight
    failure: str | None = None
    http_status: int | None = None
    parsed: _LayaResponse | None = None
    started = time.perf_counter()
    try:
        async with _client_factory(timeout_s) as client:
            started = time.perf_counter()  # 클라이언트 생성 비용은 지연 측정에서 뺀다
            async with asyncio.timeout(timeout_s):
                response = await client.post(
                    url.rstrip("/") + "/v1/systemone",
                    json={
                        "state": student_input,
                        "questions": LAYA_QUESTIONS,
                        "model": _LAYA_MODEL,
                    },
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            http_status = response.status_code
            response.raise_for_status()
            parsed = _LayaResponse.model_validate(response.json())
    except (httpx.HTTPError, ValidationError, ValueError, TimeoutError) as exc:
        # 예상된 실패 부류(연결·총 시간 초과·상태·JSON·경계 스키마) — 타입명으로 원인을 남긴다.
        failure = type(exc).__name__
    except Exception as exc:  # noqa: BLE001 — 예상 밖 실패도 본류를 깨지 않는다
        failure = type(exc).__name__
    finally:
        _in_flight = max(0, _in_flight - 1)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    try:
        observation = IntentShadowObservation(
            route=route,
            rule_intent=rule_intent,
            has_solution=has_solution,
            laya_intent=parsed.answers.intent.choice if parsed else None,
            laya_confidence=parsed.answers.intent.answer_confidence if parsed else None,
            pii_prob=parsed.answers.pii.noul if parsed else None,
            routed_model=parsed.routing.model if parsed else None,
            latency_ms=latency_ms,
            failure=failure,
            http_status=http_status,
        )
    except Exception as exc:  # noqa: BLE001 — 레코드 조립 실패도 본류를 깨지 않는다
        logger.warning("의도 섀도 레코드 조립 실패: %s", type(exc).__name__)
        return
    _emit(observation)
