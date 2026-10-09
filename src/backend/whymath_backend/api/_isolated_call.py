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
from typing import Any, TypeVar

from whymath_backend.config import get_settings
from whymath_backend.l3.isolated_call import BudgetExceededError, IsolatedCallPool

__all__ = ["isolated", "isolation_stats", "reset_pool_for_tests"]

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


def reset_pool_for_tests() -> None:
    """테스트 전용 — 풀을 닫고 비운다(설정을 바꿔 다시 만들 때)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown()
            _pool = None
