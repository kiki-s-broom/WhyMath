"""tests/backend/api/test_rate_limit_fixture_isolation.py — OPS-63 전역 격리 픽스처 변별력.

`conftest.py`의 오토유즈 픽스처(`_reset_rate_limit_store_before_test`)가 실제로 무언가를
하는지, 그리고 Redis 백엔드는 건드리지 않는지를 헬퍼 함수(`conftest.reset_inmemory_rate_limit_store`)
직접 호출로 검증한다 — pytest 스케줄링·randomly 순서에 기대지 않는다(CLAUDE.md "변별력
없는 검증 스텝 금지" — 순서 의존 검증은 순서가 바뀌면 조용히 무의미해진다).

세 층위 (acceptance③-정정이 요구하는 "PG 없이 도는 hermetic 검증"이 이 파일이다):
  ① 시딩 → 헬퍼 호출 없이 한도 도달(429) 재현 — "픽스처를 끈" 상태의 실사고 재현.
  ② 헬퍼 호출 후 같은 시딩에서도 다시 허용(201 동치) — 격리가 실제로 비운다.
  ③ Redis 백엔드일 때는 헬퍼가 아무것도 하지 않는다 — acceptance① "Redis 설정은
     건드리지 않는다" 경계.

실 PG가 필요한 축(21개 통합 테스트 파일의 실제 파일 순서 재현)은 CI의 "backend —
마이그레이션·통합 (실 PG)" 잡이 이 픽스처가 적용된 채로 통과하는 것으로 간접 확인한다 —
이 파일이 직접 재는 것은 *격리 메커니즘 자체*의 변별력이다.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import pytest
from fastapi import HTTPException, Response

import conftest
from whymath_backend.api._rate_limit import (
    InMemoryBackend,
    RedisBackend,
    _enforce_by_ip,
    get_backend,
    set_backend,
)

_TEST_IP = "ops63-fixture-isolation-probe"
_WRITE_LIMIT = 60  # coach_rate_limit_ip_write_per_minute 기본값과 동일(acceptance③-정정)


@pytest.fixture(autouse=True)
def _restore_backend_after_each_test() -> Iterator[None]:
    """이 파일이 백엔드를 교체해도 다음 테스트로 새지 않게 원복한다.

    conftest의 오토유즈 픽스처는 InMemoryBackend일 때만 리셋하므로, 이 파일이 Redis 같은
    가짜 백엔드로 교체한 채 끝나면 *다음 테스트*가 리셋되지 않은 상태를 물려받는다 —
    정확히 이 태스크가 막으려는 형태의 오염을 이 테스트 파일 자신이 낼 뻔한 지점이다.
    """
    yield None
    set_backend(InMemoryBackend())


def _seed_write_hits(ip: str, count: int, *, limit: int) -> None:
    """백엔드에 write 카테고리 히트 `count`건을 직접 심는다(시딩 — acceptance③-정정)."""
    backend = get_backend()
    now = time.monotonic()
    for _ in range(count):
        asyncio.run(backend.hit_by_ip(ip, category="write", limit=limit, now=now))


class TestUnisolatedStateReproducesTheIncident:
    """① 픽스처를 끈 상태 재현 — 시딩 직후(격리 헬퍼 호출 없이) 한도가 이미 소진돼 있다."""

    def test_seeded_bucket_is_full_without_reset(self) -> None:
        assert isinstance(get_backend(), InMemoryBackend)
        _seed_write_hits(_TEST_IP, _WRITE_LIMIT, limit=999)  # 느슨한 한도로 60건 채워 넣기
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                _enforce_by_ip(_TEST_IP, category="write", limit=_WRITE_LIMIT, response=Response())
            )
        assert exc_info.value.status_code == 429


class TestFixtureHelperClearsInMemoryBackend:
    """② 헬퍼(`reset_inmemory_rate_limit_store`) 호출 후 같은 시딩에서도 다시 허용된다."""

    def test_reset_after_seeding_allows_next_request(self) -> None:
        _seed_write_hits(_TEST_IP, _WRITE_LIMIT, limit=999)
        conftest.reset_inmemory_rate_limit_store()
        # 예외가 나지 않으면(429 없이 반환) 리셋이 실제로 비웠다는 뜻이다.
        asyncio.run(
            _enforce_by_ip(_TEST_IP, category="write", limit=_WRITE_LIMIT, response=Response())
        )

    def test_autouse_fixture_leaves_backend_empty_at_test_start(self) -> None:
        """이 테스트 자신도 오토유즈 픽스처의 수혜자다 — 시작 시점에 잔여가 없어야 한다.

        앞선 테스트(들)가 같은 프로세스에서 이 IP를 채웠더라도, conftest의 오토유즈
        픽스처가 이 테스트 시작 전에 비웠어야 한다.
        """
        backend = get_backend()
        assert isinstance(backend, InMemoryBackend)
        result = asyncio.run(
            backend.hit_by_ip(_TEST_IP, category="write", limit=1, now=time.monotonic())
        )
        assert result.allowed is True  # 이전 테스트의 잔여가 있었다면 여기서 거부됐을 것


class TestRedisBackendIsUntouched:
    """③ Redis(대역) 백엔드일 때는 헬퍼가 아무것도 하지 않는다 — acceptance① 경계."""

    def test_redis_backend_reset_not_invoked(self) -> None:
        class _SpyBackend(RedisBackend):
            def __init__(self) -> None:
                super().__init__()
                self.reset_called = False

            async def reset(self) -> None:  # pragma: no cover — 호출되면 안 되는 경로
                self.reset_called = True
                await super().reset()

        spy = _SpyBackend()
        set_backend(spy)
        conftest.reset_inmemory_rate_limit_store()
        assert spy.reset_called is False
