"""API 계층의 격리 호출 진입점 — `isolated(...)` 하나(OPS-96).

핸들러가 `async def`인데 CPU를 오래 쓰는 검증 계산을 동기로 부르면 느린 입력 1건이 그 워커의
모든 요청을 멈춘다. 이 모듈은 그 호출을 `l3.isolated_call`의 프로세스 풀로 옮기고, **상한 초과를
호출부가 지정한 판정 불가 값으로 접는다**(`on_budget_exceeded`) — 통과·오답으로 접는 경로가 없다는
것이 이 헬퍼의 계약이다. 호출부가 판정 불가 값을 *필수 인자로* 넘기게 해서, 새 호출 지점이 "초과
시 무엇을 돌려줄 것인가"를 빠뜨릴 수 없다.

설정 `sympy_isolation_enabled=False`면 종전처럼 인라인 동기 실행(완전 되돌리기).
풀은 프로세스 전역 단일 인스턴스를 첫 호출에 만든다(워커 상주 비용을 앱 수명 동안 한 번만 치른다).
워커가 미리 import할 모듈은 설정(`sympy_isolation_preload_modules`)이 정한다 — 이 Core 모듈은
과목 어휘를 알지 못한다.
"""

from __future__ import annotations

import atexit
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from whymath_backend.config import get_settings
from whymath_backend.l3.isolated_call import BudgetExceededError, IsolatedCallPool

__all__ = [
    "IsolationServedSnapshot",
    "isolated",
    "isolation_served_snapshot",
    "isolation_stats",
    "reset_pool_for_tests",
]

logger = logging.getLogger("whymath.api.isolated_call")

T = TypeVar("T")

_pool: IsolatedCallPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> IsolatedCallPool:
    """프로세스 전역 풀 — 첫 호출에 설정값으로 만든다(이중 확인 잠금)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                settings = get_settings()
                _pool = IsolatedCallPool(
                    max_workers=settings.sympy_isolation_max_workers,
                    timeout_s=settings.sympy_isolation_timeout_s,
                    preload=tuple(settings.sympy_isolation_preload_modules),
                )
                atexit.register(_pool.shutdown)
    return _pool


async def isolated(
    fn: Callable[..., T],
    *args: Any,
    on_budget_exceeded: Callable[[], T],
    timeout_s: float | None = None,
    **kwargs: Any,
) -> T:
    """`fn(*args, **kwargs)`를 이벤트 루프 밖에서 시간 상한과 함께 실행한다.

    상한 초과·대기열 포화·워커 사망은 `on_budget_exceeded()`의 반환값(= 호출부의 *판정 불가*
    값)으로 접는다. `fn`이 던진 예외(`ValueError` 등)는 그대로 전파된다 — 호출부의 입력 오류
    계약(422 변환)이 격리 여부와 무관하게 같다. `timeout_s`는 이 호출의 상한을 설정값보다 *낮출*
    때만 쓴다(체인의 남은 예산 등 — `fn`에는 전달되지 않는다).
    """
    if not get_settings().sympy_isolation_enabled:
        return fn(*args, **kwargs)
    try:
        return await _get_pool().run(fn, *args, timeout_s=timeout_s, **kwargs)
    except BudgetExceededError as exc:
        # 침묵 실패 금지 — 사유 코드(타입명 포함)를 남긴다. 호출 인자(학생 입력)는 싣지 않는다.
        logger.warning(
            "isolation_budget_exceeded reason=%s limit_s=%g (%s) → 판정 불가",
            exc.reason,
            exc.limit_s,
            type(exc).__name__,
        )
        return on_budget_exceeded()


def isolation_stats() -> dict[str, int]:
    """풀의 누적 카운터 — 풀이 아직 없으면 빈 dict. "격리가 실제로 작동한 비율" 관측용."""
    return _pool.stats() if _pool is not None else {}


@dataclass(frozen=True, slots=True)
class IsolationServedSnapshot:
    """격리가 *작동한 비율*의 불변 스냅샷 — `/health/ready`의 `sympy_isolation` 섹션 원천(OPS-126).

    정상 응답 200은 격리가 일했다는 증거가 아니다(CLAUDE.md "작동한 비율" 원칙). 격리 경로에 들어온
    시도(`attempts = calls + fallbacks`)는 정확히 셋 중 하나로 끝난다:
      - `served`    — 워커 프로세스 안에서 끝까지 계산됐다(= `calls - folded`)
      - `folded`    — 상한 초과·대기열 포화·워커 사망으로 **판정 불가로 접혔다**
      - `fallbacks` — pickle 불가로 스레드 실행됐다(**격리가 적용되지 않았고 시간 상한도 없다**)
    그래서 세 비율의 합이 1이다. `folded_ratio`가 오르면 상한이 정상 입력을 판정 불가로 떨어뜨리고
    있다는 신호이고, `fallback_ratio`가 0이 아니면 격리를 우회한 호출 지점이 있다는 신호다.

    **한계(명시)**
      - 카운터는 **프로세스별**이다. 서버 워커(uvicorn `--workers`)가 여럿이면 이 값은 응답을 낸 그
        프로세스의 것이고 합산이 아니다(`ops/service_health.ServiceMetrics`와 같은 전제). 재시작하면
        0으로 돌아간다.
      - `served`는 스냅샷 시점에 *진행 중인* 호출을 포함한다(`calls`는 시작 시 오른다). 오차 상한은
        동시 호출 수(≤ max_workers + 대기열)이므로 표본이 수백 건 이상이면 무시할 수 있다.
      - `sympy_isolation_enabled=False`면 호출이 인라인으로 돌아 카운터가 서지 않는다 — 비율은
        `None`이다(0%가 아니라 "이 인스턴스는 격리를 켜지 않았다").

    비율은 **분모가 0이면 `None`** 이다 — 모르면 모른다(0.0으로 접으면 "접힌 적 없음"으로 읽힌다).
    """

    enabled: bool
    pool_started: bool
    attempts: int
    served: int
    folded_timeout: int
    folded_queue_wait: int
    folded_worker_died: int
    fallbacks: int
    served_ratio: float | None
    folded_ratio: float | None
    fallback_ratio: float | None

    @property
    def folded(self) -> int:
        """판정 불가로 접힌 호출 수 — 사유 3종의 합."""
        return self.folded_timeout + self.folded_queue_wait + self.folded_worker_died


def isolation_served_snapshot() -> IsolationServedSnapshot:
    """`isolation_stats()`를 읽어 격리가 작동한 비율을 낸다 — 예외를 던지지 않는다.

    풀이 아직 없으면(첫 격리 호출 전) 카운터는 전부 0이고 `pool_started=False`다. 이때 비율은
    `None`이다 — "아직 시도가 없었다"와 "전부 성공했다"가 같은 화면이 되지 않게 한다.
    """
    enabled = get_settings().sympy_isolation_enabled
    stats = isolation_stats()
    calls = stats.get("calls", 0)
    timeouts = stats.get("timeouts", 0)
    queue_waits = stats.get("queue_waits", 0)
    worker_deaths = stats.get("worker_deaths", 0)
    fallbacks = stats.get("fallbacks", 0)
    folded = timeouts + queue_waits + worker_deaths
    attempts = calls + fallbacks
    served = max(calls - folded, 0)
    measurable = enabled and attempts > 0
    return IsolationServedSnapshot(
        enabled=enabled,
        pool_started=_pool is not None,
        attempts=attempts,
        served=served,
        folded_timeout=timeouts,
        folded_queue_wait=queue_waits,
        folded_worker_died=worker_deaths,
        fallbacks=fallbacks,
        served_ratio=served / attempts if measurable else None,
        folded_ratio=folded / attempts if measurable else None,
        fallback_ratio=fallbacks / attempts if measurable else None,
    )


def reset_pool_for_tests() -> None:
    """테스트 전용 — 풀을 닫고 비운다(설정을 바꿔 다시 만들 때)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown()
            _pool = None
