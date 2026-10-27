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
- **비차단**: 판정은 학생 턴 커밋 *뒤* `_spawn`(create_task)으로 띄우고 즉시 반환한다 — 학생 응답
  지연에 laya 왕복이 더해지지 않는다. 판정 코루틴은 모든 예외를 흡수한다.
- **침묵 실패 금지**: 흡수한 예외는 *예외 타입명*과 HTTP 상태 코드를 로그·레코드에 남긴다. 실패도
  레코드 1건으로 남겨 "작동한 비율"을 잴 수 있게 한다(성공만 기록하면 실패율이 0으로 위장된다).
- **프라이버시**: 학생 원문·원문 해시·세션/학생 식별자를 레코드와 로그에 넣지 않는다(미성년자
  채팅 평문 저장 금지). 원문은 메모리에서 자체 호스팅 laya-serve로만 전송된다.
- **보조 신호**: 개인정보 확률은 관측값일 뿐 PII 보호 절차를 대체하지 않는다(법령 유래 절차의
  기계 대체 금지). 이 레코드를 근거로 무언가를 자동으로 가리거나 차단하지 않는다.

**레이어**: laya-serve는 HTTP 외부 프로세스라 L4(순수 계층)에 둘 수 없다. 서빙 계층(`api`)의
비공개 모듈로 두고, L4의 규칙 분류기 결과는 *값*으로만 받는다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from whymath_backend.config import Settings, get_settings
from whymath_backend.l4.misconception.shadow import _spawn
from whymath_backend.schema.enums import StudentIntent

logger = logging.getLogger("whymath.api.intent_shadow")
# 구조화 레코드 JSON 한 줄 — 평문 로그와 분리된 자식 로거(step_shadow.record 동형).
record_logger = logging.getLogger("whymath.api.intent_shadow.record")

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
    """`POST /v1/systemone` 응답의 경계 스키마 — 검사를 못 넘은 응답은 레코드에 싣지 않는다."""

    model_config = ConfigDict(extra="ignore")

    answers: _Answers
    routing: _Routing


class IntentShadowObservation(BaseModel):
    """의도 섀도 관측 1건 — record_logger로 JSON 한 줄 emit.

    **담지 않는 것**: 학생 원문·원문 해시·dialogue/student/session 식별자. 일치도 측정에는 두
    분류기의 라벨 쌍만 필요하고, 식별자가 있으면 레코드가 학생 대화와 다시 결합될 수 있다.
    """

    model_config = ConfigDict(extra="forbid")

    route: ShadowRoute
    """어느 엔드포인트의 학생 턴인지 — 세션 첫 턴과 이후 턴의 분포가 다를 수 있어 나눠 본다."""

    rule_intent: StudentIntent | None
    """규칙 분류기 결과(DB에 실제로 적재된 값). 빈 첫 진입 턴이면 None."""

    has_solution: bool
    """풀이 제출 동반 여부 — 규칙 분류기의 `답시도` 판정 입력이라 비교 해석에 필요하다."""

    laya_intent: LayaIntent | None = None
    laya_confidence: float | None = None
    pii_prob: float | None = None
    routed_model: str | None = None

    questions_version: str = QUESTIONS_VERSION
    latency_ms: float
    """laya 왕복 + 검사 시간. 실패여도 기록한다(타임아웃 근처 분포 확인용)."""

    failure: str | None = None
    """실패 시 예외 타입명(`ConnectError`·`ReadTimeout`·`HTTPStatusError`·`ValidationError` 등)."""

    http_status: int | None = None
    """응답을 받았을 때의 HTTP 상태 — `HTTPStatusError` 하나로 401·503이 같은 글자로 보이지 않게."""

    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 테스트 주입 좌석 — 기본은 실제 httpx 클라이언트. 테스트는 `httpx.MockTransport`를 끼운
# 클라이언트 팩토리로 바꿔 라이브 서버 없이 성공·실패 경로를 전부 재현한다(wh1_shadow_probe 선례).
ClientFactory = Callable[[float], httpx.AsyncClient]


def _default_client_factory(timeout_s: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout_s)


_client_factory: ClientFactory = _default_client_factory


def set_client_factory(factory: ClientFactory | None) -> None:
    """테스트용 — None이면 기본 팩토리로 되돌린다."""
    global _client_factory
    _client_factory = factory if factory is not None else _default_client_factory


def shadow_configured(settings: Settings) -> bool:
    """섀도가 실제로 호출할 조건 — 스위치 + URL + 키가 *모두* 있어야 한다.

    하나라도 비면 False(외부 호출 0회). 키 없는 호출을 허용하면 무인증 서버로 학생 발화가
    나갈 수 있고, URL 없는 호출은 매 턴 실패 레코드만 쌓는다 — 둘 다 켜지지 않는 편이 맞다.
    """
    return bool(
        settings.laya_intent_shadow_enabled
        and settings.laya_intent_shadow_url.strip()
        and settings.laya_intent_shadow_api_key.get_secret_value().strip()
    )


def spawn_intent_shadow(
    *,
    student_input: str,
    rule_intent: StudentIntent | None,
    has_solution: bool,
    route: ShadowRoute,
) -> None:
    """학생 턴 1건의 섀도 판정을 *백그라운드로* 띄우고 즉시 반환한다. 반환 None(비노출).

    꺼져 있거나 설정이 덜 됐거나 발화가 비어 있으면 task를 만들지 않는다. 이 함수 자체도
    본류를 깨지 않는다 — 설정 조회·task 생성 실패까지 흡수하고 타입명을 남긴다.
    """
    try:
        settings = get_settings()
        if not shadow_configured(settings) or not student_input.strip():
            return
        _spawn(
            observe_intent_shadow(
                student_input=student_input,
                rule_intent=rule_intent,
                has_solution=has_solution,
                route=route,
                url=settings.laya_intent_shadow_url,
                api_key=settings.laya_intent_shadow_api_key.get_secret_value(),
                timeout_s=settings.laya_intent_shadow_timeout_s,
            )
        )
    # 관측 방어선 — 섀도는 본류를 안 깬다(비차단 불변)
    except Exception as exc:  # noqa: BLE001
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

    never-break: HTTP·파싱·경계 검사·직렬화·로깅 전부를 흡수한다. 실패 레코드에는 예외 타입명과
    (있으면) HTTP 상태를 싣는다 — 원인이 남지 않는 실패는 측정 회차만 태운다.
    """
    started = time.perf_counter()
    failure: str | None = None
    http_status: int | None = None
    parsed: _LayaResponse | None = None
    try:
        async with _client_factory(timeout_s) as client:
            response = await client.post(
                url.rstrip("/") + "/v1/systemone",
                json={"state": student_input, "questions": LAYA_QUESTIONS, "model": _LAYA_MODEL},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            http_status = response.status_code
            response.raise_for_status()
            parsed = _LayaResponse.model_validate(response.json())
    except (httpx.HTTPError, ValidationError, ValueError) as exc:
        # 예상된 실패 부류(연결·타임아웃·상태·JSON·경계 스키마) — 타입명으로 원인을 남긴다.
        failure = type(exc).__name__
    except Exception as exc:  # noqa: BLE001 — 예상 밖 실패도 본류를 깨지 않는다
        failure = type(exc).__name__
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
        if failure is not None:
            logger.warning("의도 섀도 판정 실패(비노출): %s http_status=%s", failure, http_status)
        record_logger.info(observation.model_dump_json())
    except Exception as exc:  # noqa: BLE001 — 기록 실패도 본류를 깨지 않는다
        logger.warning("의도 섀도 기록 실패: %s", type(exc).__name__)
