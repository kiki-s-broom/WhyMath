"""CPU 집약 호출의 이벤트 루프 격리 + 시간 상한 — 별도 프로세스 워커 풀(OPS-96).

**왜 필요한가** — `async def` 핸들러 안에서 CPU를 오래 쓰는 동기 계산을 그대로 부르면 단일 이벤트
루프가 멈춰, 느린 입력 1건이 그 워커의 *모든* 학생 요청을 막는다(지연 문제를 넘은 가용성 결함).
입력 길이·구조 예산 같은 *결정론적* 상한은 있어도 **시간 상한은 따로 필요하다** — 구조 예산을
통과하고도 수 초~십수 초 걸리는 입력이 실재한다(실측 2026-10-02 `verify_step`의 방정식 단계:
차수 20 계수 1 ≈3.0초, 같은 차수에 계수 7919 ≈10초·123457 ≈17초). 이 모듈은 그 *뒤*의 마지막
방어선이다. 과목 어휘를 모르는 범용 장치다 — 무엇을 격리할지는 호출부가 정한다.

**격리 방식 판정 — 스레드가 아니라 프로세스** (실측: `tests/backend/l3/test_isolated_call.py`)
  - 스레드(`asyncio.to_thread`)는 루프 정지를 풀어 주지만(실측 최대 정지 0.021초) **강제 중단이
    불가능**하다 — 상한을 넘긴 계산이 스레드에서 끝날 때까지 CPU를 계속 쓴다(실측: 상한 0.5초
    초과 뒤 1.5초 동안 프로세스 CPU 1.93초 추가 소모). 그러면 "CPU 시간 상한"이 성립하지 않는다.
  - 프로세스는 상한 초과 시 `kill`로 계산을 실제로 끊는다. 비용은 워커 상시 보유(import 비용은
    워커 기동 시 한 번)와 인자·결과의 pickle 왕복(밀리초 미만)이다.

**판정 의미 — 상한 초과는 `BudgetExceededError`** — 이 모듈은 예외로만 알린다. 호출부가 *자기
도메인의 판정 불가 값*으로 접는다. 검증 계산이라면 통과로 접으면 검증 우회고 오답으로 접으면
학생에게 부당한 부정 피드백이다(교수학 금기) — 그래서 접는 값은 반드시 "모른다"다. 시간 상한은
*판정이 아니라 가용성 장치*라서 같은 입력의 결과가 기계 부하로 달라질 수 있다 — 결과는 항상
"모른다"로만 떨어지고 다른 값으로 바뀌지 않는다.

**설계**
  - 워커 `max_workers`개를 `spawn`으로 띄운다(Windows·Linux 공통 — fork는 다중 스레드 서버에서
    위험하고 Windows에는 없다). 워커는 `preload` 모듈을 import한 뒤 `ready`를 보낸다.
  - **상한은 계산 시간만 잰다** — 워커 기동과 호출 대상 복원(unpickle, 첫 호출 시 모듈 import
    수백 ms)은 상한 밖이다. 워커가 복원을 끝내고 `started`를 알린 뒤부터 잰다(실측: 이 분리가
    없으면 첫 호출의 정상 입력이 상한 0.5초에 걸려 판정 불가로 샜다).
  - 호출 하나 = 워커 하나 점유. 대기열이 `queue_wait_s`를 넘으면 그것도 `BudgetExceededError`
    (`reason="queue_wait"`)다. 상한 초과 시 워커를 `kill`하고 교체 워커를 *미리* 띄운다.
  - 호출 대상은 `pickle` 가능한 함수·메서드와 인자여야 한다. 불가능하면 *조용히 막지 않고*
    스레드로 폴백하며 예외 타입명을 경고 로그에 남기고 `fallback_count`를 올린다 — 폴백은
    격리가 아니라 "루프는 덜 막는" 차선이고 상한이 없다는 사실을 숨기지 않기 위해서다.
  - 워커 안의 예외는 같은 타입으로 되던진다(`ValueError`→422 같은 호출부 계약 보존). pickle이
    안 되는 예외는 `WorkerError`로 감싼다.

**로그** — 예외 타입명·사유 코드만 싣는다. 호출 인자(학생 입력)는 싣지 않는다(미성년 PII).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import multiprocessing
import os
import pickle
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

__all__ = [
    "DEFAULT_TIMEOUT_S",
    "IsolatedCallPool",
    "BudgetExceededError",
    "WorkerError",
]

logger = logging.getLogger("whymath.l3.isolated_call")

T = TypeVar("T")

DEFAULT_TIMEOUT_S = 5.0
"""호출 하나의 계산 시간 상한(초) — 워커가 일을 받은 순간부터. 실측 근거는 설정값
(`config.Settings.sympy_isolation_timeout_s`) 주석을 본다."""

_STARTUP_TIMEOUT_S = 60.0
"""워커 기동(`spawn` + 사전 import) 대기 상한 — 이걸 넘기면 워커 자체가 고장이다."""


class BudgetExceededError(Exception):
    """시간 상한 초과 또는 대기열 포화 — **판정 불가**다(통과·오답이 아니다).

    `reason`은 `"timeout"`(계산이 상한을 넘겨 워커를 끊음)·`"queue_wait"`(워커가 모두 바빠
    대기 상한을 넘김)·`"worker_died"`(워커가 도중에 죽음) 중 하나다. 호출부는 어느 경우든 같은
    판정 불가로 접되, 로그·지표에서는 사유를 구분한다.
    """

    def __init__(self, reason: Literal["timeout", "queue_wait", "worker_died"], limit_s: float):
        super().__init__(f"isolated call budget exceeded: {reason} (limit {limit_s:g}s)")
        self.reason = reason
        self.limit_s = limit_s


class WorkerError(RuntimeError):
    """워커 안에서 난 예외를 그대로 되던질 수 없을 때(pickle 불가) 감싸는 예외 — 타입명 보존."""


# ── 워커 프로세스 쪽 ──────────────────────────────────────────────────────────────


def _worker_main(conn: Any, preload: tuple[str, ...]) -> None:
    """워커 루프 — `(fn, args, kwargs)` pickle을 받아 실행하고 결과·예외를 돌려준다.

    `preload` 모듈은 *첫 호출*이 아니라 여기서 미리 import해 `ready` 전에 기동 비용을 치른다.
    부모가 죽거나 파이프가 닫히면(EOF) 조용히 끝난다 — 고아 워커를 남기지 않는다.
    """
    for module_name in preload:
        importlib.import_module(module_name)

    conn.send(("ready", os.getpid()))
    while True:
        try:
            payload = conn.recv_bytes()
        except (EOFError, OSError):
            return
        try:
            fn, args, kwargs = pickle.loads(payload)
            # 복원(unpickle)은 호출 대상의 모듈을 *처음* import할 수 있다(어댑터 트리 등 수백 ms).
            # 그 시간은 계산이 아니므로 상한 밖이다 — 복원이 끝났음을 알린 *뒤*부터 부모가
            # 상한을 잰다.
            conn.send_bytes(pickle.dumps(("started",)))
            result = fn(*args, **kwargs)
            out: tuple[Any, ...] = ("ok", result)
        except BaseException as exc:  # noqa: BLE001 — 워커는 어떤 예외도 부모에 되돌려야 한다
            out = ("err", exc)
        try:
            conn.send_bytes(pickle.dumps(out))
        except Exception as exc:  # 결과/예외가 pickle 불가
            what = type(out[1]).__name__ if out[0] == "err" else "result"
            conn.send_bytes(pickle.dumps(("werr", type(exc).__name__, what)))


# ── 부모 프로세스 쪽 ──────────────────────────────────────────────────────────────


@dataclass(eq=False)  # 동일성 해시 — 집합에 담는다
class _Worker:
    """워커 한 개 — 프로세스와 부모 쪽 파이프 끝."""

    process: Any
    conn: Any
    ready: bool = False


class IsolatedCallPool:
    """CPU 집약 호출을 별도 프로세스에서 시간 상한과 함께 돌리는 워커 풀.

    사용: `await pool.run(fn, *args, timeout_s=...)`. 상한 초과면 `BudgetExceededError`.
    풀은 이벤트 루프에 묶이지 않는다 — 한 번 만들어 앱 수명 동안 쓰고 `shutdown()`으로 닫는다.
    워커는 **첫 `run`에서 지연 기동**한다(테스트·격리를 안 쓰는 경로에서 프로세스를 낭비하지 않음).
    """

    def __init__(
        self,
        *,
        max_workers: int = 2,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        queue_wait_s: float | None = None,
        preload: tuple[str, ...] = (),
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers는 1 이상이어야 한다.")
        if timeout_s <= 0:
            raise ValueError("timeout_s는 0보다 커야 한다.")
        self._max_workers = max_workers
        self._preload = preload
        self.timeout_s = timeout_s
        # 대기열 상한 기본값 = 시간 상한 × 2 — 앞 호출이 상한까지 쓰는 최악을 한 번은 기다린다.
        self.queue_wait_s = queue_wait_s if queue_wait_s is not None else timeout_s * 2
        self._ctx = multiprocessing.get_context("spawn")
        self._lock = threading.Lock()
        self._idle: deque[_Worker] = deque()
        self._all: set[_Worker] = set()
        self._io = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="isolated-call")
        # 이벤트 루프별 세마포어(테스트가 루프를 바꾼다)
        self._sems: dict[int, asyncio.Semaphore] = {}
        self._closed = False
        # 관측 카운터 — 응답이 "격리가 작동한 비율"을 말할 수 있게(알고리즘 부착 ≠ 작동 원칙).
        self.calls = 0
        self.timeouts = 0
        self.queue_waits = 0
        self.worker_deaths = 0
        self.fallback_count = 0

    # -- 공개 API --------------------------------------------------------------

    async def run(
        self,
        fn: Callable[..., T],
        *args: Any,
        timeout_s: float | None = None,
        **kwargs: Any,
    ) -> T:
        """`fn(*args, **kwargs)`를 워커 프로세스에서 실행한다.

        상한 초과는 `BudgetExceededError`다.

        `fn`·인자·반환값은 pickle 가능해야 한다. 불가능하면 스레드로 폴백한다(모듈 docstring).
        """
        if self._closed:
            raise RuntimeError("IsolatedCallPool이 이미 닫혔다.")
        limit = self.timeout_s if timeout_s is None else timeout_s
        try:
            payload = pickle.dumps((fn, args, kwargs))
        except Exception as exc:
            # 조용한 우회 금지 — 타입명을 남기고 폴백을 센다. 학생 입력은 싣지 않는다.
            self.fallback_count += 1
            logger.warning(
                "격리 폴백 — 호출 대상 pickle 불가(%s): 스레드 실행·시간 상한 없음",
                type(exc).__name__,
            )
            return await asyncio.to_thread(fn, *args, **kwargs)

        self.calls += 1
        sem = self._semaphore()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self.queue_wait_s)
        except TimeoutError:
            self.queue_waits += 1
            logger.warning("격리 대기열 포화 — %.1fs 초과(판정 불가로 접힘)", self.queue_wait_s)
            raise BudgetExceededError("queue_wait", self.queue_wait_s) from None
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._io, self._roundtrip, payload, limit)
        finally:
            sem.release()

    def shutdown(self) -> None:
        """모든 워커를 끊고 풀을 닫는다 — 앱 종료 시 호출(고아 프로세스 방지)."""
        self._closed = True
        with self._lock:
            workers = list(self._all)
            self._all.clear()
            self._idle.clear()
        for worker in workers:
            self._kill(worker)
        self._io.shutdown(wait=False, cancel_futures=True)

    def stats(self) -> dict[str, int]:
        """누적 카운터 — 호출 수·상한 초과·대기 포화·워커 사망·폴백."""
        return {
            "calls": self.calls,
            "timeouts": self.timeouts,
            "queue_waits": self.queue_waits,
            "worker_deaths": self.worker_deaths,
            "fallbacks": self.fallback_count,
        }

    # -- 내부 -----------------------------------------------------------------

    def _semaphore(self) -> asyncio.Semaphore:
        loop_id = id(asyncio.get_running_loop())
        sem = self._sems.get(loop_id)
        if sem is None:
            sem = asyncio.Semaphore(self._max_workers)
            self._sems[loop_id] = sem
        return sem

    def _spawn(self) -> _Worker:
        parent, child = self._ctx.Pipe(duplex=True)
        process = self._ctx.Process(target=_worker_main, args=(child, self._preload), daemon=True)
        process.start()
        child.close()  # 부모는 자식 쪽 끝을 닫아야 자식 종료 시 EOF를 본다
        worker = _Worker(process=process, conn=parent)
        with self._lock:
            self._all.add(worker)
        return worker

    def _acquire(self) -> _Worker:
        with self._lock:
            if self._idle:
                return self._idle.popleft()
        return self._spawn()

    def _release(self, worker: _Worker) -> None:
        with self._lock:
            if not self._closed:
                self._idle.append(worker)

    def _kill(self, worker: _Worker) -> None:
        try:
            worker.process.kill()
        except Exception as exc:
            logger.warning("격리 워커 kill 실패(%s)", type(exc).__name__)
        try:
            worker.conn.close()
        except Exception:
            pass
        try:
            worker.process.join(timeout=2.0)
        except Exception:
            pass
        with self._lock:
            self._all.discard(worker)

    def _prewarm_replacement(self) -> None:
        """kill한 자리를 *미리* 채운다 — 교체 워커의 import(≈0.8초)가 응답 뒤에 겹쳐 진행된다.

        다음 호출이 곧바로 오면 `ready`를 기다리지만(기동은 상한 밖), 간격이 있으면 대기가 사라진다.
        """
        if self._closed:
            return
        try:
            self._release(self._spawn())
        except Exception as exc:  # 교체 실패는 다음 호출이 지연 기동으로 메운다 — 타입명만 남긴다
            logger.warning(
                "격리 교체 워커 선기동 실패(%s) — 다음 호출에서 기동", type(exc).__name__
            )

    def _wait_ready(self, worker: _Worker) -> bool:
        """워커의 `ready`를 기다린다(기동 시간은 상한 밖). 실패하면 False."""
        if worker.ready:
            return True
        try:
            if worker.conn.poll(_STARTUP_TIMEOUT_S) and worker.conn.recv()[0] == "ready":
                worker.ready = True
                return True
        except (EOFError, OSError):
            pass
        return False

    def _roundtrip(self, payload: bytes, limit_s: float) -> Any:
        """워커에 일을 맡기고 상한까지 기다린다 — I/O 스레드에서 실행(이벤트 루프 밖)."""
        worker = self._acquire()
        if not self._wait_ready(worker):
            self._kill(worker)
            self.worker_deaths += 1
            logger.error("격리 워커 기동 실패 — ready 미수신")
            raise BudgetExceededError("worker_died", _STARTUP_TIMEOUT_S)
        try:
            worker.conn.send_bytes(payload)
            # 1단계 — 워커가 호출 대상을 복원(unpickle)할 때까지. 모듈 첫 import 비용이 여기
            # 들어가고 상한 밖이다(계산이 아니다). 단 무한정은 아니다 — 기동 상한을 넘기면
            # 워커 고장으로 본다.
            if not worker.conn.poll(_STARTUP_TIMEOUT_S):
                self._kill(worker)
                self.worker_deaths += 1
                logger.error("격리 워커 복원 단계 무응답 — 판정 불가로 접힘")
                raise BudgetExceededError("worker_died", _STARTUP_TIMEOUT_S)
            reply = pickle.loads(worker.conn.recv_bytes())
            if reply[0] == "started":
                # 2단계 — 여기부터가 *계산 시간*이다. 상한 초과는 계산을 실제로 끊는다(스레드로는
                # 못 하는 것). 끊은 워커는 교체된다.
                started = time.perf_counter()
                if not worker.conn.poll(limit_s):
                    self.timeouts += 1
                    logger.warning(
                        "계산 시간 상한 초과 — %.1fs(워커 kill·판정 불가로 접힘)",
                        time.perf_counter() - started,
                    )
                    self._kill(worker)
                    self._prewarm_replacement()
                    raise BudgetExceededError("timeout", limit_s)
                reply = pickle.loads(worker.conn.recv_bytes())
            # `started` 없이 바로 err/werr면 복원 단계 예외(ImportError 등) — 그대로 되돌린다.
            kind, *rest = reply
        except BudgetExceededError:
            raise
        except (EOFError, OSError) as exc:
            self.worker_deaths += 1
            logger.error("격리 워커 사망(%s) — 판정 불가로 접힘", type(exc).__name__)
            self._kill(worker)
            raise BudgetExceededError("worker_died", limit_s) from None
        self._release(worker)
        if kind == "ok":
            return rest[0]
        if kind == "err":
            raise rest[0]
        # "werr" — 결과·예외가 pickle 불가였다. 타입명만 보존해 알린다.
        raise WorkerError(f"워커 결과 직렬화 실패({rest[0]}, 대상 {rest[1]})")
