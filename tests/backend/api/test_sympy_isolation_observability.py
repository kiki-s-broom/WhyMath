"""SymPy 격리가 *작동한 비율*의 운영 관측 — `/health/ready` `sympy_isolation` 섹션(OPS-126 ①).

배경: `api/_isolated_call.isolation_stats()`는 풀 호출 수·상한 초과·대기열 포화·워커 사망·폴백
카운터를 만들지만 이를 읽는 비테스트 코드가 0건이었다(선언만 있고 배선이 없는 상태). 정상 응답
200은 격리가 일했다는 증거가 아니므로(CLAUDE.md "작동한 비율" 원칙) 응답이 두 비율을 말해야 한다.

동결 계약:
  1. **변별력(단위)** — 비율이 분모 0이면 `None`이고(None-vs-0), 폴백·상한 초과가 있으면 각각
     `isolated_ratio < 1`·`undecidable_ratio > 0`로 *다르게* 드러난다.
  2. **라이브 결선** — 실 verify 요청이 실 풀 카운터를 올리고, 그것이 `/health/ready`에 그대로 보인다.
     상한 초과 요청은 `undecidable_ratio`로, 정상 요청은 0으로 가려진다(양방향).
  3. **격리 끔** — `sympy_isolation_enabled=false`면 호출이 인라인이라 카운터가 서지 않고 비율은 null이다
     (정상 응답이 격리 작동으로 오독되지 않는다).
  4. **소비자 배선** — `health_ready` 핸들러가 `isolation_snapshot()`을 실제로 부른다(AST).
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.api import _isolated_call
from whymath_backend.api._auth import get_consented_user
from whymath_backend.api._isolated_call import IsolationSnapshot, isolation_snapshot
from whymath_backend.app import create_app
from whymath_backend.config import get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.ops.service_health import (
    COMPONENT_DATABASE,
    COMPONENT_LLM_ROUTER,
    COMPONENT_REDIS,
    ComponentCheck,
    ReadinessProbes,
)
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_SLOW_A = "x^20+x+1=0"
_SLOW_B = "x^19+x+2=0"
_CAP_S = 0.5


def _snapshot(**overrides: Any) -> IsolationSnapshot:
    base: dict[str, Any] = {
        "enabled": True,
        "pool_started": True,
        "process_id": 1,
        "max_workers": 2,
        "timeout_s": 5.0,
        "calls": 0,
        "timeouts": 0,
        "queue_waits": 0,
        "worker_deaths": 0,
        "fallbacks": 0,
    }
    base.update(overrides)
    return IsolationSnapshot(**base)


# ──────────────────────────────────────────────────────────────────────────
# ① 변별력(단위) — 분모 0 = None, 사유가 다르면 신호가 다르다.
# ──────────────────────────────────────────────────────────────────────────
class TestIsolationSnapshotRatios:
    def test_no_traffic_ratios_are_none_not_zero(self) -> None:
        """호출이 없으면 비율은 None(측정 대상 없음)이다 — 0.0('전부 정상')과 구분된다."""
        snap = _snapshot()
        assert snap.undecidable_ratio is None
        assert snap.isolated_ratio is None
        assert snap.undecidable == 0

    def test_clean_traffic_is_zero_undecidable_and_fully_isolated(self) -> None:
        """호출 20건·접힘 0·폴백 0 ⇒ undecidable_ratio=0.0(None 아님)·isolated_ratio=1.0."""
        snap = _snapshot(calls=20)
        assert snap.undecidable_ratio == 0.0
        assert snap.isolated_ratio == 1.0

    def test_three_fold_reasons_sum_into_undecidable(self) -> None:
        """상한 초과 2 + 대기열 포화 1 + 워커 사망 1 ⇒ 4/40 = 0.1 — 사유 합산."""
        snap = _snapshot(calls=40, timeouts=2, queue_waits=1, worker_deaths=1)
        assert snap.undecidable == 4
        assert snap.undecidable_ratio == pytest.approx(0.1)

    def test_fallbacks_lower_isolated_ratio_but_not_undecidable(self) -> None:
        """폴백은 풀 밖(상한 없음)이라 isolated_ratio만 깎고 undecidable_ratio는 안 건드린다."""
        snap = _snapshot(calls=30, fallbacks=10)
        assert snap.isolated_ratio == pytest.approx(0.75)
        assert snap.undecidable_ratio == 0.0

    def test_fallback_only_traffic_is_zero_isolated_and_undecidable_none(self) -> None:
        """전부 폴백(풀에 맡겨진 호출 0) ⇒ isolated_ratio=0.0이고 undecidable_ratio는 None."""
        snap = _snapshot(fallbacks=5)
        assert snap.isolated_ratio == 0.0
        assert snap.undecidable_ratio is None

    def test_reasons_yield_pairwise_distinct_signatures(self) -> None:
        """무트래픽·정상·상한초과·폴백 네 상태가 (undecidable_ratio, isolated_ratio)로 서로 구분된다."""
        signatures = {
            (s.undecidable_ratio, s.isolated_ratio)
            for s in (
                _snapshot(),
                _snapshot(calls=10),
                _snapshot(calls=10, timeouts=1),
                _snapshot(calls=10, fallbacks=10),
            )
        }
        assert len(signatures) == 4


class _StubPool:
    """`isolation_snapshot()`이 풀의 `stats()`를 읽는지 보는 스텁 — 워커를 띄우지 않는다."""

    def __init__(self, stats: dict[str, int]) -> None:
        self._stats = stats

    def stats(self) -> dict[str, int]:
        return self._stats

    def shutdown(self) -> None:
        return None


class TestIsolationSnapshotReadsPool:
    @pytest.fixture(autouse=True)
    def _clean_pool(self) -> Iterator[None]:
        _isolated_call.reset_pool_for_tests()
        get_settings.cache_clear()
        yield
        _isolated_call.reset_pool_for_tests()
        get_settings.cache_clear()

    def test_pool_not_started_reports_zero_counters_and_flag(self) -> None:
        """풀이 아직 없으면 pool_started=False·카운터 0 — 스냅샷 조회가 풀을 만들지도 않는다."""
        snap = isolation_snapshot()
        assert snap.pool_started is False
        assert snap.calls == 0
        assert _isolated_call._pool is None  # 읽기가 풀을 기동하지 않는다

    def test_snapshot_mirrors_pool_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """풀의 다섯 카운터가 스냅샷 필드에 키 이름대로 옮겨진다(키 오배선 변별)."""
        stub = _StubPool(
            {"calls": 11, "timeouts": 2, "queue_waits": 3, "worker_deaths": 4, "fallbacks": 5}
        )
        monkeypatch.setattr(_isolated_call, "_pool", stub)
        snap = isolation_snapshot()
        assert snap.pool_started is True
        assert (
            snap.calls,
            snap.timeouts,
            snap.queue_waits,
            snap.worker_deaths,
            snap.fallbacks,
        ) == (
            11,
            2,
            3,
            4,
            5,
        )
        # 서로 다른 값을 줬으므로 두 필드를 바꿔 꽂는 오배선이면 여기서 깨진다.
        assert snap.undecidable == 9

    def test_snapshot_carries_configured_cap_and_workers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """상한·워커 수는 *설정값*을 싣는다 — 비율을 해석할 때 어떤 상한에서 나온 값인지 알 수 있다."""
        monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
        monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_TIMEOUT_S", "7.5")
        monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_MAX_WORKERS", "3")
        get_settings.cache_clear()
        snap = isolation_snapshot()
        assert snap.timeout_s == 7.5
        assert snap.max_workers == 3


# ──────────────────────────────────────────────────────────────────────────
# ② 라이브 결선 — 실 verify 요청 → 실 풀 카운터 → /health/ready.
# ──────────────────────────────────────────────────────────────────────────
class _FakeSession:
    async def execute(self, stmt: Any) -> None:
        raise AssertionError("verify 라우터(stateless)는 DB 쿼리하지 않아야 한다.")


def _fake_probes() -> ReadinessProbes:
    async def _check(name: str, required: bool) -> ComponentCheck:
        return ComponentCheck(
            name=name, configured=True, reachable=True, required=required, error=None
        )

    async def _db() -> ComponentCheck:
        return await _check(COMPONENT_DATABASE, True)

    async def _redis() -> ComponentCheck:
        return await _check(COMPONENT_REDIS, False)

    async def _llm() -> ComponentCheck:
        return await _check(COMPONENT_LLM_ROUTER, False)

    return ReadinessProbes(database=_db, redis=_redis, llm=_llm)


def _app() -> Any:
    app = create_app(readiness_probes=_fake_probes())
    user = UserProfile.from_schema(
        UserProfileSchema(user_id=uuid.uuid4(), persona_primary=Persona.A_일반고고3)
    )
    app.dependency_overrides[get_consented_user] = lambda: user

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _sess
    return app


def _configure(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> None:
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_TIMEOUT_S", str(_CAP_S))
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_MAX_WORKERS", "1")
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()


@pytest.fixture
def isolation_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _configure(monkeypatch, enabled=True)
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def isolation_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _configure(monkeypatch, enabled=False)
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


def _ready_section(client: TestClient) -> dict[str, Any]:
    resp = client.get("/health/ready")
    assert resp.status_code == 200, resp.text
    section = resp.json()["sympy_isolation"]
    assert isinstance(section, dict)
    return section


@pytest.mark.usefixtures("isolation_on")
class TestReadyReportsServedRatio:
    def test_before_any_traffic_pool_not_started_and_ratios_null(self) -> None:
        """격리 호출 전에는 pool_started=False·calls=0·두 비율 null(0.0 아님)."""
        with TestClient(_app()) as client:
            section = _ready_section(client)
        assert section["enabled"] is True
        assert section["pool_started"] is False
        assert section["calls"] == 0
        assert section["undecidable_ratio"] is None
        assert section["isolated_ratio"] is None

    def test_normal_then_slow_step_shows_up_in_the_ratio(self) -> None:
        """정상 1건 + 상한 초과 1건 ⇒ calls=2·timeouts=1·undecidable_ratio=0.5, 폴백 0이라 isolated=1.0.

        정상 입력만 보냈을 때(앞 단언)는 undecidable_ratio=0.0이므로 이 단언이 변별한다 —
        200 응답은 둘 다 같지만 `/health/ready`가 접힘을 드러낸다.
        """
        with TestClient(_app()) as client:
            ok = client.post(
                "/v1/verify-step", json={"expr_before": "2*(x+1)", "expr_after": "2*x+2"}
            )
            assert ok.status_code == 200 and ok.json()["state"] == "correct"
            clean = _ready_section(client)
            assert clean["pool_started"] is True
            assert clean["calls"] == 1
            assert clean["undecidable"] == 0
            assert clean["undecidable_ratio"] == 0.0
            assert clean["isolated_ratio"] == 1.0

            slow = client.post(
                "/v1/verify-step", json={"expr_before": _SLOW_A, "expr_after": _SLOW_B}
            )
            assert slow.status_code == 200 and slow.json()["state"] == "unverifiable"
            folded = _ready_section(client)

        assert folded["calls"] == 2
        assert folded["timeouts"] == 1
        assert folded["undecidable"] == 1
        assert folded["undecidable_ratio"] == pytest.approx(0.5)
        assert folded["isolated_ratio"] == 1.0
        assert folded["fallbacks"] == 0
        assert folded["timeout_s"] == _CAP_S

    def test_section_reports_process_id_for_per_process_counters(self) -> None:
        """카운터는 프로세스별 — 응답이 pid를 실어 워커를 가린다(다중 워커 합산의 전제)."""
        import os

        with TestClient(_app()) as client:
            section = _ready_section(client)
        assert section["process_id"] == os.getpid()

    def test_ready_gate_is_unaffected_by_isolation_observation(self) -> None:
        """격리 접힘이 있어도 ready 판정(200)은 DB 도달성만 따른다 — 관측은 게이트가 아니다."""
        with TestClient(_app()) as client:
            client.post("/v1/verify-step", json={"expr_before": _SLOW_A, "expr_after": _SLOW_B})
            resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True


@pytest.mark.usefixtures("isolation_off")
class TestIsolationOffIsNotMistakenForServed:
    def test_inline_execution_leaves_counters_zero_and_ratios_null(self) -> None:
        """격리를 끄면 verify가 200을 돌려줘도 카운터가 서지 않고 enabled=False·비율 null이다.

        바로 위 `isolation_on` 클래스에서는 같은 요청이 calls=1을 만든다 — 200 응답만으로는
        격리가 일했는지 알 수 없다는 것(이 태스크의 전제)과, 이 섹션이 그 둘을 가른다는 것의 대조군.
        """
        with TestClient(_app()) as client:
            resp = client.post(
                "/v1/verify-step", json={"expr_before": "2*(x+1)", "expr_after": "2*x+2"}
            )
            assert resp.status_code == 200 and resp.json()["state"] == "correct"
            section = _ready_section(client)
        assert section["enabled"] is False
        assert section["pool_started"] is False
        assert section["calls"] == 0
        assert section["undecidable_ratio"] is None
        assert section["isolated_ratio"] is None


# ──────────────────────────────────────────────────────────────────────────
# ③ 소비자 배선 — 비테스트 코드가 isolation_snapshot()을 실제로 부른다.
# ──────────────────────────────────────────────────────────────────────────
def _called_names(fn: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


class TestConsumerWiring:
    def test_health_ready_handler_calls_isolation_snapshot(self) -> None:
        """`health_ready` 핸들러 본문이 `isolation_snapshot()`을 호출한다 — 선언만 있는 상태의 재발 방지.

        스캔 0건은 실패다(핸들러를 못 찾으면 공허 통과가 아니라 즉시 실패).
        """
        app_py = Path(_isolated_call.__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(app_py.read_text(encoding="utf-8"))
        handlers = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "health_ready"
        ]
        assert len(handlers) == 1, "health_ready 핸들러를 정확히 1개 찾아야 한다"
        assert "isolation_snapshot" in _called_names(handlers[0])

    def test_isolation_snapshot_has_a_non_test_consumer(self) -> None:
        """`isolation_snapshot`(= `isolation_stats`의 소비 창구)을 읽는 비테스트 코드가 있다.

        이 태스크가 닫은 '카운터는 만드는데 읽는 곳이 0건'의 동결. 스캔 대상이 0건이면 실패.
        """
        src_root = Path(_isolated_call.__file__).resolve().parents[1]
        files = [p for p in src_root.rglob("*.py") if p.name != "_isolated_call.py"]
        assert files, "스캔 대상 소스가 0건이다"
        consumers = [p for p in files if "isolation_snapshot" in p.read_text(encoding="utf-8")]
        assert consumers, "isolation_snapshot의 비테스트 소비자가 0건이다"
