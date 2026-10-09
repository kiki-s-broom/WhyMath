"""`l3.isolated_call` 단위테스트 — 프로세스 격리·시간 상한·판정 불가(OPS-96).

**실제 워커 프로세스**를 띄운다(가짜 없음) — 격리의 본질이 프로세스 경계라서 시임으로는 아무것도
증명되지 않는다. 느린 입력은 합성 sleep이 아니라 *실제 SymPy가 느린 식*(`x^20+x+1=0`·`safe_parse`
구조 예산 상한 차수의 방정식 단계 — 실측 약 3초)이다.

실측으로 정한 설계 판정(모듈 docstring ②):
  - 스레드는 루프를 풀어 주지만 상한 초과 후에도 계산이 끊기지 않는다(`test_thread_cannot_stop`
    가 그 대조군 — 프로세스 방식이 필요한 이유의 기계 증거).
"""

from __future__ import annotations

import asyncio
import functools
import os
import time

import pytest

from whymath_backend.l3.isolated_call import (
    BudgetExceededError,
    IsolatedCallPool,
)
from whymath_backend.l3.verify_step import verify_step

# 구조 예산(`MAX_POLY_DEGREE=20`)을 통과하는 가장 느린 부류 — 이 환경 실측 약 3.0초.
_SLOW = ("x^20+x+1=0", "x^19+x+2=0")
_FAST = ("2*(x+1)", "2*x+2")


def _unique_slow(degree: int) -> tuple[str, str]:
    """프로세스 안에서 *처음 보는* 느린 방정식 단계 — 계수를 시각 기반으로 고유하게 만든다.

    SymPy는 같은 입력을 내부 캐시에 두어 재호출이 0.05초로 끝난다(실측: 첫 호출 10~17초 → 같은
    입력 재호출 0.05초). 프로세스 안에서 직접 돌리는 대조군이 앞선 테스트의 캐시에 적중하면 느린
    입력이 빠르게 끝나 *대조군이 변별하지 못한다* — 테스트 순서(무작위화)에 따라 깨지는 가짜 통과/
    실패를 막으려고 대조군은 항상 고유 입력을 쓴다. 차수 12≈2.2초·13≈2.9초(이 환경 실측).
    """
    k = time.time_ns() % 1_000_000 + 2
    return f"x^{degree}+{k}*x+1=0", f"x^{degree - 1}+{k}*x+2=0"


@pytest.fixture
def pool() -> IsolatedCallPool:
    p = IsolatedCallPool(max_workers=1, timeout_s=0.5, queue_wait_s=0.3)
    yield p
    p.shutdown()


async def _warm(p: IsolatedCallPool) -> None:
    """워커 기동(SymPy import)을 시간 상한 밖에서 미리 치른다 — 상한 측정이 기동에 오염되지 않게."""
    await p.run(verify_step, *_FAST)


class TestBasics:
    async def test_normal_call_returns_result(self, pool: IsolatedCallPool) -> None:
        result = await pool.run(verify_step, *_FAST)
        assert result.state.value == "correct"
        assert pool.stats()["calls"] == 1

    async def test_worker_exception_propagates_with_same_type(self, pool: IsolatedCallPool) -> None:
        """워커 안의 `ValueError`가 같은 타입으로 되던져진다 — 호출부의 422 변환 계약이 같다."""
        from whymath_backend.l3.verify_solution import plan_transitions

        with pytest.raises(ValueError, match="step_types 길이"):
            await pool.run(plan_transitions, ["a", "b", "c"], [None])


class TestBudget:
    async def test_over_cap_raises_budget_exceeded_and_cuts_the_computation(
        self, pool: IsolatedCallPool
    ) -> None:
        """④ⓐ 상한 초과 → `BudgetExceededError(timeout)` — 상한 근처에서 끊긴다(3초를 안 기다림)."""
        await _warm(pool)
        started = time.perf_counter()
        with pytest.raises(BudgetExceededError) as info:
            await pool.run(verify_step, *_SLOW)
        elapsed = time.perf_counter() - started
        assert info.value.reason == "timeout"
        assert elapsed < 2.0, f"상한 0.5s인데 {elapsed:.2f}s — 계산이 끊기지 않았다"
        assert pool.stats()["timeouts"] == 1

    async def test_worker_is_replaced_after_kill(self, pool: IsolatedCallPool) -> None:
        """상한 초과로 죽인 뒤에도 풀이 정상 회복한다 — 다음 호출이 새 워커에서 성공."""
        await _warm(pool)
        with pytest.raises(BudgetExceededError):
            await pool.run(verify_step, *_SLOW)
        result = await pool.run(verify_step, *_FAST)
        assert result.state.value == "correct"

    async def test_worker_process_is_really_killed(self, pool: IsolatedCallPool) -> None:
        """'끊었다'가 사실인지 — 상한 초과 뒤 그 워커 프로세스가 살아 있지 않다(CPU를 계속 쓰지 않음)."""
        await _warm(pool)
        before = {w.process for w in pool._all}
        with pytest.raises(BudgetExceededError):
            await pool.run(verify_step, *_SLOW)
        assert before, "워커가 하나도 없었다 — 검사가 공허하다"
        assert all(not proc.is_alive() for proc in before)

    async def test_event_loop_stays_responsive_during_slow_call(
        self, pool: IsolatedCallPool
    ) -> None:
        """④ⓑ 느린 식이 도는 동안 같은 루프의 다른 일이 막히지 않는다(최대 정지 < 0.3초).

        대조: 같은 입력을 루프 안에서 동기로 돌리면 약 3초 멈춘다(실측 2.96초) — 이 테스트는 그
        격리를 되돌리면(= `pool.run`을 `verify_step(...)` 직접 호출로 바꾸면) RED다.
        """
        await _warm(pool)
        gaps: list[float] = []
        stop = asyncio.Event()

        async def ticker() -> None:
            last = time.perf_counter()
            while not stop.is_set():
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0.05)
        with pytest.raises(BudgetExceededError):
            await pool.run(verify_step, *_SLOW)
        stop.set()
        await task
        assert len(gaps) > 20, "ticker가 거의 돌지 못했다 — 루프가 막혔다"
        assert max(gaps) < 0.3, f"루프 최대 정지 {max(gaps):.2f}s"

    async def test_queue_saturation_raises_queue_wait(self, pool: IsolatedCallPool) -> None:
        """워커가 모두 바쁘면 대기 상한 뒤 `queue_wait` — 이것도 판정 불가다(통과 아님)."""
        await _warm(pool)
        slow = asyncio.create_task(pool.run(verify_step, *_SLOW, timeout_s=3.0))
        await asyncio.sleep(0.1)
        with pytest.raises(BudgetExceededError) as info:
            await pool.run(verify_step, *_FAST)
        assert info.value.reason == "queue_wait"
        slow.cancel()
        await asyncio.gather(slow, return_exceptions=True)

    async def test_worker_death_is_reported_not_swallowed(self, pool: IsolatedCallPool) -> None:
        """워커가 도중에 죽으면 `worker_died` — 침묵하지도, 결과를 지어내지도 않는다."""
        await _warm(pool)
        with pytest.raises(BudgetExceededError) as info:
            await pool.run(functools.partial(os._exit, 1))
        assert info.value.reason == "worker_died"
        assert pool.stats()["worker_deaths"] == 1
        # 죽은 뒤에도 회복한다.
        assert (await pool.run(verify_step, *_FAST)).state.value == "correct"


class TestFallback:
    async def test_unpicklable_callable_falls_back_to_thread_and_counts(
        self, pool: IsolatedCallPool, caplog: pytest.LogCaptureFixture
    ) -> None:
        """pickle 불가 호출 대상은 조용히 막지 않고 스레드로 폴백 — 카운트·경고 로그(타입명)로 드러난다."""
        with caplog.at_level("WARNING", logger="whymath.l3.isolated_call"):
            result = await pool.run(lambda: 41 + 1)
        assert result == 42
        assert pool.stats()["fallbacks"] == 1
        assert any("pickle 불가" in r.message and "Error" in r.message for r in caplog.records)


class TestThreadIsNotEnough:
    """② 판정의 대조군 — 스레드는 루프를 풀어 줄 뿐 상한 초과 후 계산을 끊지 못한다."""

    async def test_thread_cannot_stop_the_computation(self) -> None:
        slow = _unique_slow(13)  # 캐시 적중 방지 — 프로세스 안에서 직접 돌리는 유일한 테스트
        started_cpu = time.process_time()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.to_thread(verify_step, *slow), timeout=0.5)
        # 상한(0.5s)을 넘겼는데 스레드의 SymPy 계산은 계속 CPU를 쓴다.
        await asyncio.sleep(1.5)
        burned = time.process_time() - started_cpu
        assert burned > 1.5, f"스레드가 끊겼다면 CPU 사용이 이만큼 많을 수 없다({burned:.2f}s)"
