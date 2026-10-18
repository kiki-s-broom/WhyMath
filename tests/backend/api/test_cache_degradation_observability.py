"""캐시 회로 차단이 *작동한 비율*의 운영 관측 — `/health/ready` `cache_degradation` 섹션(OPS-149 ③).

왜 이 테스트가 필요한가: 정상 응답 200은 우회가 일했다는 증거가 아니다(CLAUDE.md 「작동 신호 없는
알고리즘 부착 금지」). Redis가 죽어도 `/health/ready`는 Redis를 `required=false`로 보고 200을 낸다 —
그래서 회로가 열려 캐시 연산이 전부 건너뛰어지는 중에도 응답 코드는 같다. 우회가 일했는지는
이 섹션의 숫자만이 말한다. 이 테스트는 그 숫자가 **실제 프로세스 회계를 읽는지**(상수가 아닌지)와
**필드가 서로 바뀌지 않았는지**를 고정한다.

변별력:
  1. 서로 다른 값(실패 3·건너뜀 4·성공 2)을 흘려 넣어 필드 취급이 뒤바뀌면 단정이 깨지게 한다.
  2. 회로가 *열린* 상태에서도 200임을 단정해, "200이면 정상"이 증거가 못 됨을 문서화한다.
  3. 연산이 없을 때 비율은 0.0이 아니라 null이다(None-vs-0).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from whymath_backend.app import _cache_degradation_body, create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.cache import RedisCache
from whymath_backend.l3.cache.redis_cache import (
    CacheDegradationSnapshot,
    reset_cache_degradation,
)
from whymath_backend.ops.service_health import (
    COMPONENT_DATABASE,
    COMPONENT_LLM_ROUTER,
    COMPONENT_REDIS,
    ComponentCheck,
    ReadinessProbes,
)


class _BoomError(RuntimeError):
    """테스트 전용 예외 — `last_error_type`에 이 *이름*이 실려야 타입명 보고가 증명된다."""


class _DeadClient:
    """get/set이 즉시 예외를 던지는 죽은 Redis(호출 기록 포함)."""

    def __init__(self) -> None:
        self.calls = 0

    async def get(self, name: str) -> Any:
        self.calls += 1
        raise _BoomError("redis 연결 실패(모사)")

    async def set(self, name: str, value: str, *, ex: int | None = None) -> Any:
        self.calls += 1
        raise _BoomError("redis 연결 실패(모사)")

    async def ping(self) -> Any:
        raise _BoomError("redis 연결 실패(모사)")


class _HealthyClient:
    async def get(self, name: str) -> Any:
        return None

    async def set(self, name: str, value: str, *, ex: int | None = None) -> Any:
        return True

    async def ping(self) -> Any:
        return True


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


@pytest.fixture(autouse=True)
def _isolated_process_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """프로세스 전역 캐시 회계를 테스트마다 비운다 — 앞 테스트의 우회가 뒤 단정을 오염시키지 않게."""
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    get_settings.cache_clear()
    reset_cache_degradation()
    yield
    reset_cache_degradation()
    get_settings.cache_clear()


def _ready(client: TestClient) -> tuple[int, dict[str, Any]]:
    resp = client.get("/health/ready")
    section = resp.json()["cache_degradation"]
    assert isinstance(section, dict)
    return resp.status_code, section


class TestReadyReportsBreakerRatio:
    def test_before_any_cache_traffic_the_ratio_is_null_not_zero(self) -> None:
        """연산 0건: 비율은 null(측정 대상 없음)이고 회로는 닫혀 있다."""
        with TestClient(create_app(readiness_probes=_fake_probes())) as client:
            status_code, section = _ready(client)

        assert status_code == 200
        assert section["scope"] == "per_process"
        assert section["breaker_open"] is False
        assert section["bypass_ratio"] is None
        assert (section["skipped_calls"], section["failures"], section["successes"]) == (0, 0, 0)
        assert section["last_error_type"] is None

    def test_open_circuit_is_visible_even_though_ready_stays_200(self) -> None:
        """회로가 열려 캐시가 전부 건너뛰어지는 중에도 응답은 200 — 숫자만이 우회를 말한다."""
        dead = _DeadClient()

        async def _drive() -> None:
            cache = RedisCache(client=dead, settings=Settings())  # 전역 카운터를 쓴다(기본)
            healthy = RedisCache(client=_HealthyClient(), settings=Settings())
            await healthy.get("k")  # 성공 1
            await healthy.get("k")  # 성공 2 (같은 전역 회계에 합산)
            for _ in range(3):
                await cache.get("k")  # 실패 3 → 회로 열림
            for _ in range(4):
                await cache.get("k")  # 건너뜀 4

        asyncio.run(_drive())
        assert dead.calls == 3  # 우회 구간에는 Redis에 한 번도 닿지 않았다

        with TestClient(create_app(readiness_probes=_fake_probes())) as client:
            status_code, section = _ready(client)

        assert status_code == 200  # 정상 200은 우회의 증거가 못 된다
        assert section["breaker_open"] is True
        assert section["breaker_opens"] == 1
        # 필드가 서로 바뀌면(실패↔건너뜀↔성공) 아래 세 단정 중 하나가 깨진다.
        assert section["failures"] == 3
        assert section["skipped_calls"] == 4
        assert section["successes"] == 2
        assert section["consecutive_failures"] == 3
        assert section["last_error_type"] == "_BoomError"
        assert section["bypass_ratio"] == pytest.approx(4 / 9)


class TestBodyMapping:
    def test_every_snapshot_field_lands_in_its_own_body_field(self) -> None:
        """서로 다른 값으로 변환을 찔러 필드 매핑이 뒤바뀌지 않았음을 고정한다."""
        snapshot = CacheDegradationSnapshot(
            get_failures=5,
            set_failures=2,
            consecutive_failures=7,
            last_error_type="TimeoutError",
            successes=11,
            breaker_opens=3,
            skipped_calls=13,
            breaker_open=True,
        )

        body = _cache_degradation_body(snapshot)

        assert body.scope == "per_process"
        assert body.breaker_open is True
        assert body.breaker_opens == 3
        assert body.skipped_calls == 13
        assert body.failures == 7  # get 5 + set 2
        assert body.successes == 11
        assert body.consecutive_failures == 7
        assert body.last_error_type == "TimeoutError"
        assert body.bypass_ratio == pytest.approx(13 / (11 + 7 + 13))
