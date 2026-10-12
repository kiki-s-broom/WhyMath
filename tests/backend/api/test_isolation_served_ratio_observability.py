"""SymPy 격리 *작동 비율* 관측 — `isolation_stats()` 소비자 배선 (OPS-126 acceptance ①).

배경: `api/_isolated_call.isolation_stats()`는 격리 호출 수·상한 초과·대기열 포화·워커 사망·폴백
카운터를 만들지만 이를 읽는 비테스트 코드가 0건이었다(선언만 있고 배선이 없는 상태). 정상 응답
200은 격리가 일했다는 증거가 아니므로(CLAUDE.md "작동한 비율" 원칙) `/health/ready`의
`sympy_isolation` 섹션이 비율을 말해야 한다.

동결 계약:
  1. **산술(단위)** — 시도 = 격리 실행 + 폴백이고 `served + folded + fallback = attempts`다.
     세 비율의 합이 1이며, 입력이 다르면 서로 다른 비율을 낸다(변별력).
  2. **모름 ≠ 0** — 풀 미기동·격리 꺼짐·시도 0건이면 비율은 `None`이다(0.0이 아니다).
  3. **실제 풀 결선** — 가짜가 아니라 진짜 워커 풀의 정상·상한 초과·폴백 호출이 각각 다른
     카운터를 올리고, 그 값이 `/health/ready` 응답에 그대로 실린다.
  4. **소비자 존재** — 비테스트 코드가 `isolation_stats()`를 읽는다(소비자 0건 회귀 차단).
"""

from __future__ import annotations

import ast
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api import _isolated_call
from whymath_backend.api._isolated_call import isolated, isolation_served_snapshot
from whymath_backend.app import create_app
from whymath_backend.config import get_settings
from whymath_backend.l3.verify_step import verify_step
from whymath_backend.ops.service_health import (
    COMPONENT_DATABASE,
    COMPONENT_LLM_ROUTER,
    COMPONENT_REDIS,
    ComponentCheck,
    ReadinessProbes,
)

_FAST = ("2*(x+1)", "2*x+2")
_CAP_S = 0.5
_ROOT = Path(__file__).resolve().parents[3]


class _FakePool:
    """`IsolatedCallPool.stats()` 표면만 흉내 낸다 — 산술 단위 테스트용(프로세스를 띄우지 않는다)."""

    def __init__(self, **stats: int) -> None:
        self._stats = {
            "calls": 0,
            "timeouts": 0,
            "queue_waits": 0,
            "worker_deaths": 0,
            "fallbacks": 0,
            **stats,
        }

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def shutdown(self) -> None:  # reset_pool_for_tests가 부른다
        return None


@pytest.fixture
def isolation_enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_ENABLED", "true")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_TIMEOUT_S", str(_CAP_S))
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_MAX_WORKERS", "1")
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def isolation_disabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_ENABLED", "false")
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


def _install_fake_pool(monkeypatch: pytest.MonkeyPatch, **stats: int) -> None:
    monkeypatch.setattr(_isolated_call, "_pool", _FakePool(**stats))


def _unique_slow(degree: int) -> tuple[str, str]:
    """프로세스 안에서 *처음 보는* 느린 방정식 단계 — SymPy 캐시 적중으로 빨라지는 것을 막는다
    (`test_coach_final_answer_isolation.py`와 같은 이유)."""
    k = time.time_ns() % 1_000_000 + 2
    return f"x^{degree}+{k}*x+1=0", f"x^{degree - 1}+{k}*x+2=0"


# ──────────────────────────────────────────────────────────────────────────
# ① 산술 — 시도 = 격리 실행 + 폴백, 세 비율의 합 = 1, 입력이 다르면 비율도 다르다.
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("isolation_enabled")
class TestServedRatioArithmetic:
    def test_mixed_counters_split_into_served_folded_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """calls=10(그중 타임아웃 2·대기포화 1·워커사망 3)·폴백 5 ⇒ 시도 15·작동 4·접힘 6·폴백 5.

        값이 서로 다르게 잡혀 있다(작동 4·접힘 6·폴백 5·사유 2/1/3) — 두 필드를 맞바꾸는 결함이
        같은 숫자 때문에 가려지지 않게 한다.
        """
        _install_fake_pool(
            monkeypatch, calls=10, timeouts=2, queue_waits=1, worker_deaths=3, fallbacks=5
        )
        snap = isolation_served_snapshot()
        assert snap.attempts == 15
        assert snap.served == 4
        assert (snap.folded_timeout, snap.folded_queue_wait, snap.folded_worker_died) == (2, 1, 3)
        assert snap.folded == 6
        assert snap.fallbacks == 5
        assert snap.served_ratio == pytest.approx(4 / 15)
        assert snap.folded_ratio == pytest.approx(6 / 15)
        assert snap.fallback_ratio == pytest.approx(5 / 15)

    def test_three_ratios_always_sum_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """분류가 빠짐없이 겹침 없이 갈린다 — 한 시도가 두 곳에 세이거나 새지 않는다."""
        for stats in (
            {"calls": 7},
            {"calls": 7, "timeouts": 7},
            {"calls": 9, "queue_waits": 3, "worker_deaths": 2, "fallbacks": 5},
            {"fallbacks": 3},
        ):
            _install_fake_pool(monkeypatch, **stats)
            snap = isolation_served_snapshot()
            assert snap.served_ratio is not None
            assert snap.folded_ratio is not None
            assert snap.fallback_ratio is not None
            assert snap.served_ratio + snap.folded_ratio + snap.fallback_ratio == pytest.approx(1.0)
            assert snap.served + snap.folded + snap.fallbacks == snap.attempts

    def test_distinct_situations_yield_distinct_ratio_signatures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """전부 정상 / 전부 접힘 / 전부 폴백 — 세 상황이 서로 다른 비율 서명을 낸다(변별력)."""
        signatures = set()
        for stats in ({"calls": 5}, {"calls": 5, "timeouts": 5}, {"fallbacks": 5}):
            _install_fake_pool(monkeypatch, **stats)
            snap = isolation_served_snapshot()
            signatures.add((snap.served_ratio, snap.folded_ratio, snap.fallback_ratio))
        assert signatures == {(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)}

    def test_inconsistent_counters_never_produce_negative_served(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """calls < 접힘 합이 되는 비정상 입력에서도 작동 수는 음수가 아니다(0으로 고정)."""
        _install_fake_pool(monkeypatch, calls=1, timeouts=3)
        snap = isolation_served_snapshot()
        assert snap.served == 0


# ──────────────────────────────────────────────────────────────────────────
# ② 모름 ≠ 0 — 측정할 수 없는 상태는 None이다.
# ──────────────────────────────────────────────────────────────────────────
class TestUnmeasuredIsNotZero:
    @pytest.mark.usefixtures("isolation_enabled")
    def test_pool_not_started_reports_none_ratios(self) -> None:
        """첫 격리 호출 전 — 시도 0건이라 '전부 성공'도 '접힌 적 없음'도 아니다."""
        snap = isolation_served_snapshot()
        assert snap.enabled is True
        assert snap.pool_started is False
        assert snap.attempts == 0
        assert (snap.served_ratio, snap.folded_ratio, snap.fallback_ratio) == (None, None, None)

    @pytest.mark.usefixtures("isolation_disabled")
    def test_disabled_isolation_reports_none_even_with_counters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """격리가 꺼져 있으면(인라인 실행) 카운터가 남아 있어도 비율은 None — 0%가 아니다."""
        _install_fake_pool(monkeypatch, calls=3, timeouts=1)
        snap = isolation_served_snapshot()
        assert snap.enabled is False
        assert (snap.served_ratio, snap.folded_ratio, snap.fallback_ratio) == (None, None, None)

    @pytest.mark.usefixtures("isolation_enabled")
    def test_pool_started_but_zero_attempts_reports_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_pool(monkeypatch)
        snap = isolation_served_snapshot()
        assert snap.pool_started is True
        assert snap.attempts == 0
        assert snap.served_ratio is None


# ──────────────────────────────────────────────────────────────────────────
# ③ 실제 풀 결선 — 진짜 워커 프로세스의 정상·상한 초과·폴백이 각각 다른 카운터를 올린다.
# ──────────────────────────────────────────────────────────────────────────
def _fake_probes() -> ReadinessProbes:
    """항상 성공하는 가짜 딥체크 — `/health/ready`가 실 DB/Redis/Ollama에 닿지 않게 한다."""

    def _make(name: str, *, required: bool) -> Any:
        async def _check() -> ComponentCheck:
            return ComponentCheck(
                name=name, configured=True, reachable=True, required=required, error=None
            )

        return _check

    return ReadinessProbes(
        database=_make(COMPONENT_DATABASE, required=True),
        redis=_make(COMPONENT_REDIS, required=False),
        llm=_make(COMPONENT_LLM_ROUTER, required=False),
    )


@pytest.mark.usefixtures("isolation_enabled")
class TestRealPoolAndReadyEndpoint:
    async def test_real_calls_move_distinct_counters_and_reach_health_ready(self) -> None:
        """정상 3 + 상한 초과 1 + 폴백 2 ⇒ 시도 6·작동 3·접힘 1·폴백 2, 그 값이 응답에 실린다."""
        verdicts: list[str] = []
        for _ in range(3):
            result = await isolated(verify_step, *_FAST, on_budget_exceeded=lambda: None)
            assert result is not None
            verdicts.append(result.state.value)
        assert verdicts == ["correct"] * 3  # 격리를 거쳐도 판정은 그대로

        slow = await isolated(verify_step, *_unique_slow(14), on_budget_exceeded=lambda: "접힘")
        assert slow == "접힘"  # 상한 초과는 호출부가 정한 판정 불가 값으로 접힌다

        # lambda는 pickle 불가 → 스레드 폴백(격리·시간 상한 없음). 접힘(1)과 다른 수(2)로 센다.
        assert await isolated(lambda: 7, on_budget_exceeded=lambda: -1) == 7
        assert await isolated(lambda: 8, on_budget_exceeded=lambda: -1) == 8

        snap = isolation_served_snapshot()
        assert snap.pool_started is True
        assert snap.attempts == 6
        assert snap.served == 3
        assert snap.folded_timeout == 1
        assert snap.fallbacks == 2
        assert snap.served_ratio == pytest.approx(3 / 6)
        assert snap.folded_ratio == pytest.approx(1 / 6)
        assert snap.fallback_ratio == pytest.approx(2 / 6)

        app = create_app(readiness_probes=_fake_probes())
        with TestClient(app) as client:
            resp = client.get("/health/ready")
        assert resp.status_code == 200
        body = resp.json()["sympy_isolation"]
        # 응답이 한계를 스스로 말한다 — 프로세스별 값이지 합산이 아니다.
        assert body["scope"] == "per_process"
        assert body["enabled"] is True
        assert body["pool_started"] is True
        assert body["attempts"] == 6
        assert body["served"] == 3
        assert body["folded_timeout"] == 1
        assert body["folded_queue_wait"] == 0
        assert body["folded_worker_died"] == 0
        assert body["fallbacks"] == 2
        assert body["served_ratio"] == pytest.approx(3 / 6)
        assert body["folded_ratio"] == pytest.approx(1 / 6)
        assert body["fallback_ratio"] == pytest.approx(2 / 6)

    def test_health_ready_before_any_call_says_unmeasured_not_zero(self) -> None:
        """첫 호출 전 응답 — 비율은 JSON null이고 pool_started=false (0.0으로 위장하지 않는다)."""
        app = create_app(readiness_probes=_fake_probes())
        with TestClient(app) as client:
            body = client.get("/health/ready").json()["sympy_isolation"]
        assert body["pool_started"] is False
        assert body["attempts"] == 0
        assert body["served_ratio"] is None
        assert body["folded_ratio"] is None
        assert body["fallback_ratio"] is None


@pytest.mark.usefixtures("isolation_enabled")
class TestReadyFieldMapping:
    def test_every_field_lands_in_its_own_slot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """서로 다른 값(2·3·5·7·20)을 심어 응답 필드가 각자 제 슬롯을 읽는지 가른다.

        접힘 사유 셋(타임아웃 2·대기포화 3·워커사망 5)과 폴백(7)·작동(20)이 전부 달라서, 어느 두
        필드를 맞바꾸거나 상수로 박는 결함도 이 테스트에서 값이 어긋난다.
        """
        _install_fake_pool(
            monkeypatch, calls=30, timeouts=2, queue_waits=3, worker_deaths=5, fallbacks=7
        )
        app = create_app(readiness_probes=_fake_probes())
        with TestClient(app) as client:
            body = client.get("/health/ready").json()["sympy_isolation"]
        assert body["attempts"] == 37
        assert body["served"] == 20
        assert body["folded_timeout"] == 2
        assert body["folded_queue_wait"] == 3
        assert body["folded_worker_died"] == 5
        assert body["fallbacks"] == 7
        assert body["served_ratio"] == pytest.approx(20 / 37)
        assert body["folded_ratio"] == pytest.approx(10 / 37)
        assert body["fallback_ratio"] == pytest.approx(7 / 37)


# ──────────────────────────────────────────────────────────────────────────
# ④ 소비자 존재 — 비테스트 코드가 isolation_stats()를 읽는다.
# ──────────────────────────────────────────────────────────────────────────
def _non_test_callers_of(name: str) -> list[str]:
    """`src/backend` 안에서 `name(...)`을 *호출*하는 위치(정의 제외)를 AST로 센다."""
    hits: list[str] = []
    for path in sorted((_ROOT / "src" / "backend" / "whymath_backend").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called == name:
                hits.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    return hits


class TestConsumerExists:
    def test_isolation_stats_has_a_non_test_consumer(self) -> None:
        """OPS-126 이전의 상태(소비자 0건)로 돌아가면 RED — 카운터는 만들어지는데 아무도 안 읽는다."""
        assert _non_test_callers_of("isolation_stats"), "isolation_stats()를 읽는 서빙 코드가 없다"

    def test_health_ready_consumes_the_snapshot(self) -> None:
        """스냅샷 함수를 `app.py`(/health/ready)가 실제로 호출한다 — 만들기만 하고 안 부르는 상태 차단."""
        callers = _non_test_callers_of("_isolation_served_snapshot")
        assert any(c.startswith("src/backend/whymath_backend/app.py") for c in callers), callers
