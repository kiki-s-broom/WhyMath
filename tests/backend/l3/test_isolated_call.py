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
import builtins
import functools
import logging
import os
import time

import pytest

from whymath_backend.config import Settings
from whymath_backend.l3.isolated_call import (
    BudgetExceededError,
    IsolatedCallPool,
    _run_warmup,
)
from whymath_backend.l3.verify_answer import verify_answer
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


class _SleepsOnRestore:
    """워커가 *호출 대상을 복원(unpickle)하는 동안* 잠드는 인자 — 복원 단계 대기를 만든다.

    `__reduce__`가 `time.sleep`을 가리키므로 피클에는 이 테스트 모듈이 안 실린다(자식 프로세스가
    테스트 모듈을 import할 필요가 없다). 복원된 값은 `time.sleep`의 반환값 `None`이다.
    """

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def __reduce__(self) -> tuple[object, tuple[float]]:
        return (time.sleep, (self._seconds,))


@pytest.fixture
def slow_boot(tmp_path: object, monkeypatch: pytest.MonkeyPatch):
    """import에 N초 걸리는 모듈을 만들어 `preload`로 쓸 이름을 돌려주는 공장 — 느리게 뜨는 워커 주입.

    spawn 자식은 부모의 `sys.path`를 물려받으므로 `syspath_prepend`만으로 자식이 모듈을 찾는다.
    """
    counter = {"n": 0}

    def make(seconds: float) -> str:
        counter["n"] += 1
        name = f"ops128_slow_boot_{counter['n']}"
        (tmp_path / f"{name}.py").write_text(f"import time\ntime.sleep({seconds})\n")  # type: ignore[operator]
        monkeypatch.syspath_prepend(str(tmp_path))
        return name

    return make


class TestTotalBudget:
    """OPS-128 — 호출부가 준 총 예산(`budget_s`)이 대기열·기동·복원·계산 전부를 묶는다.

    종전 결함: 기동(`_wait_ready`)·복원 대기가 계산 상한 밖이라, 체인 마감 직전에 시작한 호출이
    마감을 재기동 1회(최악 60초)만큼 넘겼다. 단계마다 *그 단계의 대기만 길게 만든* 입력으로 고정한다.
    """

    async def test_slow_boot_is_cut_at_budget_and_the_booting_worker_is_kept(
        self, slow_boot: object
    ) -> None:
        """기동 단계 — 예산 안에 `ready`가 안 오면 `deadline`이고, 뜨는 중인 워커는 죽이지 않는다."""
        pool = IsolatedCallPool(
            max_workers=1, timeout_s=0.5, queue_wait_s=0.3, preload=(slow_boot(1.5),)  # type: ignore[operator]
        )
        try:
            started = time.perf_counter()
            with pytest.raises(BudgetExceededError) as info:
                await pool.run(repr, "x", budget_s=0.4)
            elapsed = time.perf_counter() - started
            assert info.value.reason == "deadline"
            assert elapsed < 1.0, f"예산 0.4s인데 {elapsed:.2f}s — 기동 대기가 예산 밖이다"
            stats = pool.stats()
            assert stats["deadlines"] == 1 and stats["worker_deaths"] == 0
            # 고장이 아니라 아직 뜨는 중이었다 — 살려 뒀으니 다음 호출이 *그 워커*로 성공한다.
            # (`_kill`은 `_all`에서 워커를 빼므로, 빈 집합에 대한 `all(...)`은 죽였어도 참이다 —
            # 반드시 *같은 객체*가 남아 있는지로 본다.)
            booting = set(pool._all)
            assert len(booting) == 1 and all(w.process.is_alive() for w in booting)
            assert await pool.run(repr, "x") == "'x'"
            assert set(pool._all) == booting, "뜨는 중이던 워커를 버리고 새로 띄웠다"
        finally:
            pool.shutdown()

    async def test_without_budget_boot_wait_is_unchanged(self, slow_boot: object) -> None:
        """대조군 — `budget_s`가 없으면(단건 엔드포인트) 종전처럼 기동을 끝까지 기다려 성공한다."""
        pool = IsolatedCallPool(
            max_workers=1, timeout_s=0.5, preload=(slow_boot(1.0),)  # type: ignore[operator]
        )
        try:
            started = time.perf_counter()
            assert await pool.run(repr, "x") == "'x'"
            assert (
                time.perf_counter() - started >= 0.9
            ), "기동을 기다리지 않았다 — 대조군이 공허하다"
            assert pool.stats()["deadlines"] == 0
        finally:
            pool.shutdown()

    async def test_slow_restore_is_cut_at_budget_and_the_dirty_worker_is_killed(
        self, pool: IsolatedCallPool
    ) -> None:
        """복원 단계 — 일을 받은 채 복원 중인 워커는 상태가 더럽혀져 죽이고, 판정 불가(`deadline`)로 접는다."""
        assert await pool.run(repr, "warm") == "'warm'"  # 기동은 미리 치른다
        before = set(pool._all)
        started = time.perf_counter()
        with pytest.raises(BudgetExceededError) as info:
            await pool.run(repr, _SleepsOnRestore(2.0), budget_s=0.5)
        elapsed = time.perf_counter() - started
        assert info.value.reason == "deadline"
        assert elapsed < 1.2, f"예산 0.5s인데 {elapsed:.2f}s — 복원 대기가 예산 밖이다"
        assert before and all(not w.process.is_alive() for w in before)
        assert pool.stats()["deadlines"] == 1 and pool.stats()["worker_deaths"] == 0
        assert await pool.run(repr, "again") == "'again'"  # 교체 워커로 회복

    async def test_compute_limit_is_reclamped_after_boot_spent_the_budget(
        self, slow_boot: object
    ) -> None:
        """계산 시작 — 기동이 예산을 갉아먹은 만큼 계산 상한도 줄어든다(호출 상한 10초여도 예산이 우선)."""
        pool = IsolatedCallPool(
            max_workers=1, timeout_s=10.0, preload=(slow_boot(0.8),)  # type: ignore[operator]
        )
        try:
            started = time.perf_counter()
            with pytest.raises(BudgetExceededError) as info:
                await pool.run(time.sleep, 8.0, budget_s=2.0)
            elapsed = time.perf_counter() - started
            # 부하로 기동이 늦으면 계산에 닿기 전에 `deadline`으로 끝날 수 있다 — 어느 쪽이든 판정 불가.
            assert info.value.reason in ("timeout", "deadline")
            assert info.value.limit_s <= 2.0
            assert (
                elapsed < 2.0 + 0.8
            ), f"총 예산 2.0s인데 {elapsed:.2f}s — 계산 상한이 예산에 안 묶였다"
        finally:
            pool.shutdown()

    async def test_queue_wait_is_bounded_by_the_budget(self, pool: IsolatedCallPool) -> None:
        """대기열 — 예산이 대기 상한(0.3s)보다 짧으면 예산이 먼저 끊고, 사유는 `queue_wait`가 아니라 `deadline`."""
        assert await pool.run(repr, "warm") == "'warm'"
        busy = asyncio.create_task(pool.run(time.sleep, 3.0, timeout_s=3.0))
        await asyncio.sleep(0.1)
        started = time.perf_counter()
        with pytest.raises(BudgetExceededError) as info:
            await pool.run(repr, "x", budget_s=0.1)
        assert time.perf_counter() - started < 0.25
        assert info.value.reason == "deadline"
        assert pool.stats()["queue_waits"] == 0 and pool.stats()["deadlines"] == 1
        busy.cancel()
        await asyncio.gather(busy, return_exceptions=True)

    async def test_exhausted_budget_touches_no_worker(self, pool: IsolatedCallPool) -> None:
        """예산이 이미 0 이하면 워커를 띄우지도 않고 `deadline` — 지연 기동 풀이 빈 채로 남는다."""
        with pytest.raises(BudgetExceededError) as info:
            await pool.run(repr, "x", budget_s=0.0)
        assert info.value.reason == "deadline"
        assert not pool._all, "예산 소진인데 워커를 띄웠다"

    async def test_exhausted_budget_counts_as_a_folded_call(self, pool: IsolatedCallPool) -> None:
        """입구 거절도 `calls`에 들어간다 — `deadlines`만 오르면 접힘이 분모를 앞질러 '작동한 비율'이 틀린다(OPS-140).

        다른 접힘 사유(대기 포화 등)는 `calls`를 올린 *뒤* 접힌다 — 호출 하나는 정확히 한 결과로 끝난다.
        """
        with pytest.raises(BudgetExceededError):
            await pool.run(repr, "x", budget_s=0.0)
        stats = pool.stats()
        assert stats["calls"] == 1
        assert stats["deadlines"] == 1
        assert stats["deadlines"] <= stats["calls"]


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


# ── 웜업(OPS-142) ────────────────────────────────────────────────────────────────

_PROBE = "sorted(m for m in __import__('sys').modules if m.startswith('sympy'))"
"""워커 안의 `sympy` 모듈 목록 — 첫 사용 때 지연 import가 일어났는지를 *시간이 아니라 사실로* 본다."""

# 식 종류별로 첫 사용에 다른 SymPy 하위 모듈이 지연 import된다(OPS-142 실측): 덧셈 빠른 경로 →
# combinatorics·tensor, `simplify` 폴백 → physics, 방정식 → assumptions·sets.
_KINDS = (
    ("2*(x+1)", "2*x+2"),
    ("(a+b)^2", "a^2+2*a*b+b^2"),
    ("x^2-5*x+6=0", "(x-2)*(x-3)=0"),
)


def _shipped_warmup() -> tuple[str, ...]:
    """출하 기본 웜업 목록 — 설정 기본값을 그대로 쓴다(테스트가 따로 만든 목록이 아니다)."""
    factory = Settings.model_fields["sympy_isolation_warmup"].default_factory
    assert factory is not None
    return tuple(factory())  # type: ignore[call-arg]


async def _modules(p: IsolatedCallPool) -> list[str]:
    return await p.run(builtins.eval, _PROBE)


async def _exercise_every_kind(p: IsolatedCallPool) -> None:
    for before, after in _KINDS:
        await p.run(verify_step, before, after)
    await p.run(verify_answer, "x**2 - 5*x + 6 = 0", {"x": "3"})
    await p.run(verify_answer, ["x+y=3", "x-y=1"], {"x": "2", "y": "1"})


class TestWarmup:
    """워커가 `ready` 전에 대표 호출을 돌려, 첫 정상 요청이 지연 import 비용을 상한 안에서 치르지 않게 한다."""

    async def test_shipped_warmup_leaves_no_first_use_import_for_known_kinds(self) -> None:
        """웜업 뒤에는 어떤 식 종류를 처음 계산해도 새 `sympy` 모듈이 로드되지 않는다."""
        p = IsolatedCallPool(max_workers=1, preload=("sympy",), warmup=_shipped_warmup())
        try:
            before = await _modules(p)
            await _exercise_every_kind(p)
            after = await _modules(p)
        finally:
            p.shutdown()
        assert sorted(set(after) - set(before)) == []

    async def test_control_without_warmup_the_same_calls_do_import_lazily(self) -> None:
        """대조군 — 웜업이 없으면 같은 호출이 새 모듈을 끌어온다(위 테스트가 변별하는 이유)."""
        p = IsolatedCallPool(max_workers=1, preload=("sympy",))
        try:
            before = await _modules(p)
            await _exercise_every_kind(p)
            after = await _modules(p)
        finally:
            p.shutdown()
        new = set(after) - set(before)
        assert any(m.startswith("sympy.physics") for m in new), sorted(new)[:5]
        assert any(m.startswith("sympy.combinatorics") for m in new), sorted(new)[:5]

    async def test_replacement_worker_after_timeout_is_also_warm(self) -> None:
        """상한 초과로 kill된 뒤의 교체 워커도 데워져 뜬다 — 같은 비용이 다음 정상 요청에 반복되지 않는다."""
        p = IsolatedCallPool(
            max_workers=1, timeout_s=0.5, preload=("sympy",), warmup=_shipped_warmup()
        )
        try:
            with pytest.raises(BudgetExceededError) as info:
                await p.run(verify_step, *_SLOW)
            assert info.value.reason == "timeout"
            before = await _modules(p)  # 교체 워커에서 실행된다
            await _exercise_every_kind(p)
            after = await _modules(p)
            assert p.stats()["timeouts"] == 1  # 위 호출들은 상한을 넘지 않았다
        finally:
            p.shutdown()
        assert sorted(set(after) - set(before)) == []

    def test_warmup_runs_before_ready(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """웜업은 `ready`보다 먼저 끝난다 — `ready`를 받은 시점에 웜업의 흔적이 이미 있다."""
        marker = tmp_path / "warm.marker"  # type: ignore[operator]
        (tmp_path / "ops142_warm_probe.py").write_text(  # type: ignore[operator]
            f"def warm():\n    open({str(marker)!r}, 'w').write('x')\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        p = IsolatedCallPool(max_workers=1, warmup=("ops142_warm_probe:warm",))
        worker = p._spawn()
        try:
            assert p._wait_ready(worker, 60.0) == "ready"
            assert marker.exists()
        finally:
            p.shutdown()

    @pytest.mark.parametrize("spec", ["no_colon", ":fn", "mod:", ""])
    def test_malformed_warmup_spec_is_rejected_by_the_parent(self, spec: str) -> None:
        """형식 오류는 워커 안에서 조용히 사라지지 않고 풀을 만들 때 부모가 거부한다."""
        with pytest.raises(ValueError, match="모듈:함수"):
            IsolatedCallPool(max_workers=1, warmup=(spec,))

    async def test_failing_warmup_does_not_prevent_the_worker_from_serving(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """웜업은 최적화일 뿐이다 — 예외를 던져도 워커는 뜨고 정상 호출을 처리한다."""
        (tmp_path / "ops142_warm_boom.py").write_text(  # type: ignore[operator]
            "def warm():\n    raise ValueError('boom')\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        p = IsolatedCallPool(max_workers=1, warmup=("ops142_warm_boom:warm", "no_such_mod_142:f"))
        try:
            result = await p.run(verify_step, *_FAST)
        finally:
            p.shutdown()
        assert result.state.value == "correct"

    def test_warmup_failure_log_names_the_exception_type_only(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """침묵 실패 금지 — 경고에 예외 *타입명*과 지정이 남고, 예외 메시지(값)는 싣지 않는다."""
        (tmp_path / "ops142_warm_secret.py").write_text(  # type: ignore[operator]
            "def warm():\n    raise ValueError('학생입력-SECRET')\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        with caplog.at_level(logging.WARNING, logger="whymath.l3.isolated_call"):
            _run_warmup(("ops142_warm_secret:warm", "no_such_mod_142:f"))
        text = caplog.text
        assert "ValueError" in text and "ops142_warm_secret:warm" in text
        assert "ModuleNotFoundError" in text
        assert "SECRET" not in text
