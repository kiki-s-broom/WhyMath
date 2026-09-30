"""클라우드 좌석 호출 실패의 **분류**와 런타임 LOCAL 강등 **작동 신호** — 단일 좌석 (ARCH-69).

왜 이 모듈이 있는가
-------------------
1차 클라우드 좌석(기본 openrouter)으로 나간 호출이 실패하면, 종전에는 예외가 그대로 올라가
`/v1/generate`가 500이 됐다. 이 태스크는 그 실패 중 **일시적 가용성 실패**(429·5xx·타임아웃·
미설정)에 한해 LOCAL로 1회 강등한다. 강등할지 말지는 **실패의 종류**로 갈리므로, 분류가 틀리면
두 방향으로 다 나쁘다 — 강등해선 안 될 것(4xx 인증·요청 오류)을 강등하면 같은 실패가 반복되는데
LOCAL 응답이 그 원인을 가리고, 강등해야 할 것을 못 하면 학생이 500을 본다.

분류는 문자열이 아니라 **타입**으로 한다
--------------------------------------
`HttpxChatTransport`는 종전에 최종 실패를 `RuntimeError("OpenAI 호환 호출 실패 HTTP 429: …")`로
올렸다 — 상태코드가 **메시지 안에** 있어서 분류하려면 정규식으로 캐내야 했다. 그 방식은
공급사 본문이 우연히 "HTTP 429"를 담거나 문구가 바뀌면 조용히 틀린다. 그래서 상태코드를 **속성**
으로 나르는 예외(`SeatHttpError`)를 전송기가 올리고, 분류기는 타입과 구조 속성만 읽는다.
`SeatHttpError`·`SeatNotConfiguredError`는 `RuntimeError`의 하위 클래스라 종전의
`except RuntimeError`·`pytest.raises(RuntimeError, match=…)` 계약은 그대로 성립한다(메시지 무변경).

분류 함수는 이 파일 **한 곳**에만 있다(`classify_seat_failure`). 좌석(openrouter·deepseek·
anthropic)이 늘어도 분류기를 복제하지 않는다 — 좌석 쪽이 자기 실패를 이 타입으로 올린다.

작동 신호 정의도 한 곳이다 (ARCH-63 ④와 공유)
--------------------------------------------
`seat_local_degrade_rate` = **LOCAL 강등 경로를 탄 횟수 ÷ 클라우드 좌석으로 디스패치한 횟수**.
분모가 0이면 **None**이다(0.0이 아니다 — 시도가 없었던 회차와 시도했는데 강등이 0회였던
회차는 다른 사실이다). ARCH-63(Anthropic 2차 좌석)이 재개돼도 이 이름·정의를 그대로 쓴다.
`seat_primary_success_rate`·`seat_failover_rate`는 이 모듈이 정의하지 않는다(ARCH-63 몫).

이 모듈은 `l3.models`만 의존한다 — 프로바이더 모듈을 import하지 않아 프로바이더가 이 타입을
올릴 수 있다(순환 없음).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Final, get_args

from whymath_backend.l3.models import DegradeReason

__all__ = [
    "DEGRADE_REASONS",
    "LocalDegradeCounter",
    "LocalDegradeSnapshot",
    "SeatCallError",
    "SeatHttpError",
    "SeatNotConfiguredError",
    "classify_seat_failure",
    "seat_local_degrade_rate",
]

DEGRADE_REASONS: Final[tuple[str, ...]] = get_args(DegradeReason)
"""강등 사유 코드 전체 — 리포트가 사유 분포의 키를 이 목록으로 고정한다(0인 사유도 0으로 보인다)."""


# ──────────────────────────────────────────────────────────────────────────
# 좌석 호출 실패의 타입 — RuntimeError 하위라 기존 except/match 계약을 깨지 않는다
# ──────────────────────────────────────────────────────────────────────────
class SeatCallError(RuntimeError):
    """클라우드 좌석 호출 실패의 좌석 중립 기반 타입."""


class SeatHttpError(SeatCallError):
    """HTTP 응답이 실패 상태였다 — 상태코드를 **속성**으로 나른다(메시지 파싱 금지).

    전송기(`HttpxChatTransport`)가 재시도를 소진한 뒤 올린다. `str(exc)`는 종전 RuntimeError와
    같은 문구(`OpenAI 호환 호출 실패 HTTP 429: … (시도 3회)`)라 로그·기존 테스트가 그대로 읽힌다.
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code: int = status_code


class SeatNotConfiguredError(SeatCallError):
    """좌석이 미설정이라 호출 자체를 하지 못했다(키 부재·허용 공급사 없음·정책 차단).

    "미설정"은 429·5xx와 달리 **호출이 나가기 전**의 실패다. 그래도 강등 사유에 넣는 이유는
    운영자에게는 같은 결과(클라우드 답이 없다)이고, 그 상태에서 학생 대면이 500이 되는 것이
    이 태스크가 없애려는 실패이기 때문이다. 다만 강등은 **표기된다**(`not_configured`) — 키가
    빠진 배포가 LOCAL 응답으로 조용히 정상처럼 돌지 않게.
    """


# ──────────────────────────────────────────────────────────────────────────
# 분류 — 타입과 구조 속성만 읽는다
# ──────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _timeout_types() -> tuple[type[BaseException], ...]:
    """타임아웃을 뜻하는 예외 **클래스** 목록 — 내장 + 설치돼 있으면 httpx·anthropic SDK.

    SDK를 상단에서 import하지 않는 이유: 이 모듈은 hermetic 환경(SDK 미설치)에서도 import돼야
    한다(`HttpxChatTransport`가 httpx를 호출 시점에만 import하는 것과 같다). 그래서 첫 분류 때
    한 번만 시도하고 결과를 캐시한다. 설치돼 있지 않은 SDK의 타임아웃은 애초에 발생할 수 없다.

    `TimeoutError`(내장)는 `asyncio.TimeoutError`를 포함한다(Python 3.11+ 별칭).
    """
    types: list[type[BaseException]] = [TimeoutError]
    try:
        import httpx

        types.append(httpx.TimeoutException)
    except ImportError:  # pragma: no cover — 환경 의존(라이브러리 미설치)
        pass
    try:
        import anthropic

        types.append(anthropic.APITimeoutError)
    except (ImportError, AttributeError):  # pragma: no cover — 환경 의존
        pass
    return tuple(types)


def _http_status_of(exc: BaseException) -> int | None:
    """예외가 나르는 HTTP 상태코드 — 없으면 None.

    읽는 자리는 셋이며 전부 **속성**이다(메시지는 읽지 않는다):
      ① `SeatHttpError.status_code`(우리 전송기)
      ② `exc.status_code`(anthropic·openai SDK의 `APIStatusError` 계열)
      ③ `exc.response.status_code`(httpx의 `HTTPStatusError`)
    bool은 int의 서브클래스지만 상태코드가 아니다 — 배제한다.
    """
    candidates: list[object] = [getattr(exc, "status_code", None)]
    response = getattr(exc, "response", None)
    if response is not None:
        candidates.append(getattr(response, "status_code", None))
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _reason_for_status(status: int) -> DegradeReason | None:
    """상태코드 → 강등 사유. 강등 대상이 아니면 None.

    - 429 → `rate_limited`
    - 5xx → `server_error`
    - 408 → `timeout` — 408은 4xx지만 **요청 오류가 아니라 시간 초과**다(OpenRouter는 상류·
      공급사가 시간 초과일 때 408을 돌려준다). 재시도해도 같은 요청이 성립할 수 있다.
    - 그 외 4xx(400·401·402·403·404·409·422 …) → None. 요청·인증·잔액·모델 ID 오류는 **다시
      걸어도 같고**, LOCAL 응답이 그 원인을 가린다. 원 예외가 그대로 올라가야 운영자가 고친다.
    """
    if status == 429:
        return "rate_limited"
    if status == 408:
        return "timeout"
    if 500 <= status <= 599:
        return "server_error"
    return None


def classify_seat_failure(exc: BaseException) -> DegradeReason | None:
    """클라우드 좌석 호출 실패를 강등 사유로 분류한다 — **강등 대상이 아니면 None**.

    None은 "분류할 수 없음"이 아니라 "**강등하지 않는다**"는 판정이다: 4xx 요청·인증 오류,
    계약 오류(`images`·`json_schema` 미지원 등 평범한 `RuntimeError`), 관할 게이트 차단,
    정체불명 예외가 전부 여기로 떨어져 원 예외가 그대로 올라간다. **모르면 강등하지 않는다** —
    강등은 LOCAL 응답을 학생에게 내보내는 행위라, 모르는 실패를 흡수하는 쪽이 더 위험하다.

    판정 순서: ① 미설정 타입 ② 타임아웃 타입 ③ 상태코드 속성. 메시지 문자열은 읽지 않는다 —
    `RuntimeError("HTTP 429 …")` 같은 **타입 없는** 예외는 메시지에 429가 있어도 None이다.
    """
    if isinstance(exc, SeatNotConfiguredError):
        return "not_configured"
    if isinstance(exc, _timeout_types()):
        return "timeout"
    status = _http_status_of(exc)
    if status is None:
        return None
    return _reason_for_status(status)


# ──────────────────────────────────────────────────────────────────────────
# 작동 신호 — seat_local_degrade_rate (ARCH-63 ④와 공유하는 단일 정의)
# ──────────────────────────────────────────────────────────────────────────
def seat_local_degrade_rate(local_degrades: int, cloud_attempts: int) -> float | None:
    """`seat_local_degrade_rate` — 강등 경로를 탄 횟수 ÷ 클라우드 좌석 디스패치 횟수.

    **분모가 0이면 None**이다. 0.0으로 접으면 "클라우드 호출이 한 번도 없었다"가 "호출은 있었고
    강등은 0회였다"(= 좌석이 건강했다)로 읽힌다 — 정반대의 두 사실이 같은 숫자가 된다.
    분자가 분모를 넘는 입력은 계수가 깨진 것이라 **조용히 1.0으로 자르지 않고** 오류로 멈춘다.
    """
    if local_degrades < 0 or cloud_attempts < 0:
        raise ValueError(
            f"계수는 음수일 수 없다(local_degrades={local_degrades}, "
            f"cloud_attempts={cloud_attempts})"
        )
    if local_degrades > cloud_attempts:
        raise ValueError(
            f"강등 횟수({local_degrades})가 클라우드 디스패치 횟수({cloud_attempts})를 "
            "넘을 수 없다 "
            "— 계수가 깨졌다(분모는 디스패치 **직전**에 센다)."
        )
    if cloud_attempts == 0:
        return None
    return local_degrades / cloud_attempts


@dataclass(slots=True, frozen=True)
class LocalDegradeSnapshot:
    """강등 계수의 한 시점 사본 — `/status`·회차 관측이 같은 객체를 읽는다.

    `armed=False`면 이 조립에는 런타임 강등 경로가 없다(저작·측정 경로). 그때 나머지 값은 전부
    0이지만 **"강등이 0회였다"가 아니라 "강등할 수 없는 구성"**이므로 `rate`는 None이다 —
    0.0을 내면 없는 보호가 "작동했고 필요 없었다"로 읽힌다(CLAUDE.md 「작동 신호 없는 알고리즘
    부착 금지」).
    """

    armed: bool
    cloud_attempts: int = 0
    local_degrades: int = 0
    local_degrade_failures: int = 0
    """강등 경로를 탔으나 LOCAL도 실패해 원 예외가 올라간 횟수(`local_degrades`의 부분집합)."""
    by_reason: Mapping[str, int] | None = None
    """사유 코드별 강등 횟수 — 키는 항상 `DEGRADE_REASONS` 전체(0인 사유도 0으로 보인다)."""

    @property
    def rate(self) -> float | None:
        """`seat_local_degrade_rate` — 강등 미장착이거나 분모 0이면 None."""
        if not self.armed:
            return None
        return seat_local_degrade_rate(self.local_degrades, self.cloud_attempts)


class LocalDegradeCounter:
    """프로세스 안의 강등 계수기 — 스레드 안전. 워커·프로세스가 여럿이면 각자의 값이다.

    Langfuse(외부 관측)와 별개로 **인프로세스에서도** 센다 — 외부 관측 인프라가 죽었을 때 강등률이
    "0건"으로 위장되지 않게 하는 이중 회계다(CLAUDE.md 「측정·게이트 도구가 판정치를 외부 관측
    인프라에만 의존 금지」). 재시작하면 0으로 돌아가므로 누적 통계가 아니라 **이 프로세스의 현재
    작동 신호**다 — 누적은 trace의 `local_degraded` 필드를 집계하는 쪽 몫이다.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cloud_attempts = 0
        self._local_degrades = 0
        self._local_degrade_failures = 0
        self._by_reason: dict[str, int] = dict.fromkeys(DEGRADE_REASONS, 0)

    def record_cloud_attempt(self) -> None:
        """클라우드 좌석으로 **디스패치하기 직전**에 센다(분모) — 성공·실패를 가리지 않는다."""
        with self._lock:
            self._cloud_attempts += 1

    def record_degrade(self, reason: DegradeReason) -> None:
        """강등 경로를 탔다(분자). LOCAL이 성공했는지는 `record_degrade_failure`가 따로 센다."""
        with self._lock:
            self._local_degrades += 1
            self._by_reason[reason] += 1

    def record_degrade_failure(self) -> None:
        """강등 경로를 탔으나 LOCAL도 실패했다 — 학생은 강등 응답이 아니라 오류를 받았다."""
        with self._lock:
            self._local_degrade_failures += 1

    def snapshot(self, *, armed: bool) -> LocalDegradeSnapshot:
        """현재 계수의 불변 사본."""
        with self._lock:
            return LocalDegradeSnapshot(
                armed=armed,
                cloud_attempts=self._cloud_attempts,
                local_degrades=self._local_degrades,
                local_degrade_failures=self._local_degrade_failures,
                by_reason=dict(self._by_reason),
            )
