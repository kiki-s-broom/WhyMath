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
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from whymath_backend.config import get_settings
from whymath_backend.l3.isolated_call import BudgetExceededError, IsolatedCallPool

__all__ = [
    "CHAIN_BUDGET_FACTOR",
    "IsolationSnapshot",
    "isolated",
    "isolation_snapshot",
    "isolation_stats",
    "reset_pool_for_tests",
]

logger = logging.getLogger("whymath.api.isolated_call")

T = TypeVar("T")

CHAIN_BUDGET_FACTOR = 4
"""풀이 단계 연쇄 한 건의 총 시간 예산 = `sympy_isolation_timeout_s` × 이 값(OPS-96·OPS-125).

`/v1/verify-solution`(전이를 하나씩 끊어 예산을 나눠 쓴다)과 코치 턴의 연쇄 검증(체인 전체를 한
호출로 돌리고 이 값만큼의 상한을 준다)이 같은 값을 쓴다 — 두 표면이 같은 풀이에 다른 인내심을
갖지 않게 하는 단일 출처다."""

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
                    warmup=tuple(settings.sympy_isolation_warmup),
                )
                atexit.register(_pool.shutdown)
    return _pool


async def isolated(
    fn: Callable[..., T],
    *args: Any,
    on_budget_exceeded: Callable[[], T],
    timeout_s: float | None = None,
    budget_s: float | None = None,
    **kwargs: Any,
) -> T:
    """`fn(*args, **kwargs)`를 이벤트 루프 밖에서 시간 상한과 함께 실행한다.

    상한 초과·대기열 포화·워커 사망은 `on_budget_exceeded()`의 반환값(= 호출부의 *판정 불가*
    값)으로 접는다. `fn`이 던진 예외(`ValueError` 등)는 그대로 전파된다 — 호출부의 입력 오류
    계약(422 변환)이 격리 여부와 무관하게 같다. `timeout_s`는 이 호출의 *계산* 상한을 설정값과
    *다르게* 줄 때 쓴다 — 체인의 남은 예산처럼 낮추거나(OPS-96), 체인 전체를 한 호출로 돌릴 때
    총 예산(`CHAIN_BUDGET_FACTOR`배)으로 높인다(OPS-125). `fn`에는 전달되지 않는다. `budget_s`는
    이 호출 *전체*(대기열·워커 기동·복원·계산)의 벽시계 예산이다 — 체인이 자기 마감을 지키려고
    남은 예산을 넘긴다(OPS-128: 안 넘기면 기동·복원 대기가 마감 밖이라 요청이 예산을 재기동 1회만큼
    넘는다).
    """
    if not get_settings().sympy_isolation_enabled:
        return fn(*args, **kwargs)
    # `budget_s`는 체인 호출만 쓴다 — 없으면 풀 호출 모양을 종전 그대로 둔다(단건·코치 경로 불변).
    pool_extra: dict[str, float] = {} if budget_s is None else {"budget_s": budget_s}
    try:
        return await _get_pool().run(fn, *args, timeout_s=timeout_s, **pool_extra, **kwargs)
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
class IsolationSnapshot:
    """격리가 *작동한 비율*의 불변 스냅샷 — `/health/ready` `sympy_isolation` 섹션의 원천(OPS-126).

    정상 응답 200은 격리가 일했다는 증거가 아니다(CLAUDE.md "작동한 비율" 원칙). 이 스냅샷이 두
    비율을 말한다:
      - `isolated_ratio` — 격리 대상 호출 중 **실제로 시간 상한이 걸린 프로세스 풀에서 돈 비율**.
        1.0이 아니면 일부 호출이 pickle 불가로 스레드 폴백했다는 뜻이다(폴백은 상한이 없다).
      - `undecidable_ratio` — 풀에 맡겨진 호출 중 **판정 불가로 접힌 비율**(상한 초과·대기열 포화·
        워커 사망·총 예산 소진). 0이 아니면 그만큼의 정상 입력이 "모른다"로 떨어졌을 수 있다 —
        상한 재판정(`sympy_isolation_timeout_s`)의 입력이다.

    **None-vs-0** — 분모가 0이면 비율은 `None`이다("0건 중 0건"이 아니라 *측정 대상이 없었다*).
    `enabled=False`(설정 되돌림)이면 호출이 인라인으로 돌아 카운터가 서지 않으므로, 앞서 쌓인
    카운터가 남아 있어도 비율은 None이다(지금은 격리하지 않는 인스턴스를 0%로 읽지 않게).

    **한계(명시)** — 카운터는 *프로세스별*이다. 서버 워커(uvicorn `--workers`)가 여럿이면
    응답한 워커 1개의 값이며 `process_id`가 그 워커를 가린다(합산은 외부 스크레이퍼 몫).
    재시작하면 0부터다.
    `undecidable`은 호출 하나당 최대 1건씩 오른다(상한 초과·대기 포화·사망·총 예산 소진 중 하나로
    끝나므로 — 입구 거절도 `calls`를 올리고 접혀서 이 관계가 유지된다). 취소된 요청(클라이언트
    끊김)은 `calls`에는 들어가고 접힘으로 세지 않아 `undecidable_ratio`는 하한 쪽으로 기운다.

    **사유 키 목록은 풀 `stats()`와 대조된다** — 풀이 판정 불가 사유를 새로 세기 시작하면
    (OPS-125·128의 `deadlines`가 그랬다) 여기 합계에 넣지 않는 한 비율이 조용히 틀린다. 그 이탈은
    `test_sympy_isolation_observability.py`의 사유 키 동결 테스트가 막는다.
    """

    enabled: bool
    pool_started: bool
    process_id: int
    max_workers: int
    timeout_s: float
    calls: int
    timeouts: int
    queue_waits: int
    deadlines: int
    worker_deaths: int
    fallbacks: int

    @property
    def undecidable(self) -> int:
        """판정 불가로 접힌 호출 수 = 상한 초과 + 대기열 포화 + 총 예산 소진 + 워커 사망."""
        return self.timeouts + self.queue_waits + self.deadlines + self.worker_deaths

    @property
    def undecidable_ratio(self) -> float | None:
        """풀에 맡겨진 호출 중 판정 불가로 접힌 비율 — 격리가 꺼졌거나 맡겨진 호출이 없으면 None."""
        return self.undecidable / self.calls if self.enabled and self.calls > 0 else None

    @property
    def isolated_ratio(self) -> float | None:
        """격리 대상 호출 중 풀에서 실제로 돈 비율 — 격리가 꺼졌거나 대상 호출이 없으면 None."""
        total = self.calls + self.fallbacks
        return self.calls / total if self.enabled and total > 0 else None


def isolation_snapshot() -> IsolationSnapshot:
    """현재 프로세스의 격리 작동 스냅샷 — 읽기 전용(풀을 만들지 않는다)."""
    settings = get_settings()
    stats = isolation_stats()
    return IsolationSnapshot(
        enabled=settings.sympy_isolation_enabled,
        pool_started=_pool is not None,
        process_id=os.getpid(),
        max_workers=settings.sympy_isolation_max_workers,
        timeout_s=settings.sympy_isolation_timeout_s,
        calls=stats.get("calls", 0),
        timeouts=stats.get("timeouts", 0),
        queue_waits=stats.get("queue_waits", 0),
        deadlines=stats.get("deadlines", 0),
        worker_deaths=stats.get("worker_deaths", 0),
        fallbacks=stats.get("fallbacks", 0),
    )


def reset_pool_for_tests() -> None:
    """테스트 전용 — 풀을 닫고 비운다(설정을 바꿔 다시 만들 때)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown()
            _pool = None
