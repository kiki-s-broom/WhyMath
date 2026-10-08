"""POST /v1/generate 레이트리밋 단위테스트 — SEC-19 (hermetic · 라이브 서비스 없음).

이 파일이 막는 것
-----------------
`/v1/generate`는 인증(`CurrentUser`, SEC-07 D1)은 있었지만 레이트리밋 의존성이 0건인 **유일한
LLM 호출 표면**이었다(시각화·장면·코치는 리미터 보유). 인증은 *누구냐*만 가려서, 인증된 단일
계정이 반복 호출하면 LLM 비용이 그대로 나갔다. 이 파일은 그 봉인이 *실제로* 걸렸는지를 못 박는다.

변별력 설계 (CLAUDE.md "보호 장치를 실패 주입 없이 보호로 선언 금지")
-------------------------------------------------------------------
  - 429를 *세 차원 각각*(사용자·IP·기기)으로 재현한다 — 한 차원만 보면 나머지가 빠져도 통과한다.
  - 무인증 요청이 버킷을 **소모하지 않음**을 IP 차원으로 잰다. 사용자 키는 무인증이면 애초에
    없으므로 사용자 차원만으로는 "인증 전에 계수하는 회귀"를 볼 수 없다.
  - 리미터가 동의 게이트(`ConsentedUser`)를 몰래 얹지 않음을 *학부모 동의 없는 미성년자*로 잰다
    (성인 사용자는 동의 게이트도 통과하므로 구분이 안 된다).
  - 라우트가 의존성을 *선언했는지*를 라우트 표에서 직접 읽는다 — 429 동작 테스트가 부착 해제를
    놓치는 경우(전역 상태 오염 등)를 이중으로 잡는다.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whymath_backend.api._auth import get_current_user
from whymath_backend.api._degradation import DegradationCounter
from whymath_backend.api._rate_limit import (
    InMemoryBackend,
    RedisBackend,
    Subject,
    get_backend,
    rate_limit_generate,
    set_backend,
)
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import GenerationResult, RoutingDecision

_PATH = "/v1/generate"
_USER = UserProfile(user_id=uuid.uuid4())
_OTHER_USER = UserProfile(user_id=uuid.uuid4())

# LOCAL·동기 경로 — 큐를 타지 않는 가장 단순한 요청(test_app.py의 happy path와 동형).
_PAYLOAD: dict[str, Any] = {
    "request": {
        "task_type": "explain",
        "difficulty": "easy",
        "requires_reasoning": False,
        "student_subscription": "free",
        "sync": True,
    },
    "prompt": "p",
    "system": "s",
}


@pytest.fixture(autouse=True)
def _restore_backend_after_each_test() -> Iterator[None]:
    """Redis 가짜로 백엔드를 교체한 테스트가 다음 테스트로 새지 않게 원복한다.

    `conftest`의 오토유즈 픽스처는 InMemoryBackend일 때만 리셋하므로, 이 파일이 교체한 채
    끝나면 뒤 테스트가 리셋 안 된 상태를 물려받는다(test_rate_limit_fixture_isolation.py 선례).
    """
    yield None
    set_backend(InMemoryBackend())


class _Provider:
    """가짜 LLMProvider — 호출 횟수만 센다(LLM에 실제로 닿았는지의 증거)."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision
    ) -> GenerationResult:
        self.calls += 1
        return GenerationResult("원시출력")


class _Queue:
    """가짜 AsyncJobQueue — 라이브 broker 차단(hermetic). 이 파일의 요청은 큐를 안 탄다."""

    async def enqueue(self, payload: dict[str, object]) -> str:
        return "job-1"


class _FakeSession:
    """동의 조회(`scalar`→None)·소유권 기록(`add`/`commit`)만 모사 — 실 DB 진입 차단."""

    async def scalar(self, stmt: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        return None

    async def commit(self) -> None:
        return None


def _settings(*, user: int = 0, ip: int = 0, device: int = 0) -> Settings:
    """차원별 한도를 명시한 테스트 설정 — 0이면 그 차원 비활성(한 번에 한 차원만 잰다)."""
    return Settings(
        jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
        generate_rate_limit_per_minute=user,
        generate_rate_limit_ip_per_minute=ip,
        generate_rate_limit_device_per_minute=device,
    )


def _app(settings: Settings, provider: _Provider | None = None) -> Any:
    app = create_app(
        provider=provider if provider is not None else _Provider(),
        cache=InMemoryCache(),
        trace=RecordingTraceSink(),
        queue=_Queue(),
    )
    app.dependency_overrides[get_settings] = lambda: settings

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _sess
    return app


def _client(
    settings: Settings,
    *,
    user: UserProfile | None = _USER,
    provider: _Provider | None = None,
) -> TestClient:
    """`user`가 None이면 인증 오버라이드를 걸지 않는다(실제 `get_current_user` → 무토큰 401)."""
    app = _app(settings, provider)
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════════
# 1) 429 — 세 차원 각각
# ══════════════════════════════════════════════════════════════════════════
class TestEachDimensionReturns429:
    def test_user_limit_exceeded_returns_429(self) -> None:
        """사용자 분당 한도(2) 초과 → 3번째가 429. 429 응답은 재시도 안내 헤더를 싣는다."""
        client = _client(_settings(user=2))
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200

        blocked = client.post(_PATH, json=_PAYLOAD)

        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        assert blocked.headers["X-RateLimit-User-Limit"] == "2"
        assert blocked.headers["X-RateLimit-User-Remaining"] == "0"

    def test_ip_limit_exceeded_returns_429(self) -> None:
        """IP 한도(2)만 켠 상태 — 사용자·기기 차원이 꺼져 있어도 IP 차원이 막는다."""
        client = _client(_settings(ip=2))
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200

        blocked = client.post(_PATH, json=_PAYLOAD)

        assert blocked.status_code == 429
        assert blocked.headers["X-RateLimit-Ip-Limit"] == "2"

    def test_device_limit_exceeded_returns_429(self) -> None:
        """기기 한도(2)만 켠 상태 — `X-Device-Id` 단위로 막는다(공유 HMAC 비밀 미설정 = 서명 생략)."""
        client = _client(_settings(device=2))
        headers = {"X-Device-Id": "dev-sec19"}
        assert client.post(_PATH, json=_PAYLOAD, headers=headers).status_code == 200
        assert client.post(_PATH, json=_PAYLOAD, headers=headers).status_code == 200

        blocked = client.post(_PATH, json=_PAYLOAD, headers=headers)

        assert blocked.status_code == 429
        assert blocked.headers["X-RateLimit-Device-Limit"] == "2"

    def test_blocked_request_never_reaches_the_llm(self) -> None:
        """**비용 방어의 본체** — 429로 막힌 요청은 provider(LLM)를 호출하지 않는다."""
        provider = _Provider()
        client = _client(_settings(user=2), provider=provider)

        def _distinct(n: int) -> dict[str, Any]:
            # 프롬프트를 매번 다르게 — 같은 요청은 캐시 적중이라 provider를 안 부른다.
            return {**_PAYLOAD, "prompt": f"p{n}"}

        for n in range(2):
            assert client.post(_PATH, json=_distinct(n)).status_code == 200
        assert provider.calls == 2

        for n in range(2, 5):
            assert client.post(_PATH, json=_distinct(n)).status_code == 429

        assert provider.calls == 2  # 막힌 3건은 캐시 미스였는데도 LLM에 닿지 않았다

    def test_zero_limits_disable_the_limiter(self) -> None:
        """`0`=비활성(설정 계약) — 세 차원 모두 0이면 반복 호출이 막히지 않는다."""
        client = _client(_settings(user=0, ip=0, device=0))
        for _ in range(6):
            assert client.post(_PATH, json=_PAYLOAD).status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 2) 사용자 격리 · 버킷 분리
# ══════════════════════════════════════════════════════════════════════════
class TestBucketIsolation:
    def test_limit_is_per_user_not_global(self) -> None:
        """A가 한도를 소진해도 B는 막히지 않는다 — 계정별 버킷."""
        settings = _settings(user=2)
        app = _app(settings)
        client = TestClient(app)

        app.dependency_overrides[get_current_user] = lambda: _USER
        for _ in range(2):
            assert client.post(_PATH, json=_PAYLOAD).status_code == 200
        assert client.post(_PATH, json=_PAYLOAD).status_code == 429

        app.dependency_overrides[get_current_user] = lambda: _OTHER_USER
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200

    @staticmethod
    def _hit_user(category: str, *, times: int, limit: int) -> bool:
        """`_USER`의 `category` 버킷을 `times`번 친다 — 마지막 히트의 허용 여부를 돌려준다.

        시각은 리미터가 실제로 쓰는 시계(`time.monotonic()`)와 같은 것을 쓴다. 임의의 상수
        (예: 0.0)로 시딩하면 60초 윈도우 밖이라 프루닝돼 *아무것도 시딩되지 않은 것*과 같아진다.
        """

        async def _go() -> bool:
            allowed = True
            for _ in range(times):
                results = await get_backend().hit_many(
                    [Subject(kind="user", id=str(_USER.user_id), limit=limit)],
                    category=category,  # type: ignore[arg-type]
                    now=time.monotonic(),
                )
                allowed = results["user"].allowed
            return allowed

        return asyncio.run(_go())

    def test_exhausted_write_and_visualization_do_not_block_generate(self) -> None:
        """코치 write(30)·시각화(15) 버킷이 가득 차도 generate는 막히지 않는다.

        선행 단정으로 두 버킷이 *실제로 가득 찼음*을 확인한다(시딩이 윈도우 안에 들어갔는지).
        generate가 이 카테고리를 공유한다면 한도(2)보다 많은 히트를 이미 본 셈이라 429가 된다.
        """
        assert self._hit_user("write", times=30, limit=30) is True
        assert self._hit_user("write", times=1, limit=30) is False  # write 버킷 가득 참
        assert self._hit_user("visualization", times=15, limit=15) is True
        assert self._hit_user("visualization", times=1, limit=15) is False  # 시각화 버킷 가득 참

        client = _client(_settings(user=2))

        assert client.post(_PATH, json=_PAYLOAD).status_code == 200

    def test_exhausted_generate_does_not_block_write(self) -> None:
        """generate를 소진해도 **같은 사용자**의 write 버킷은 비어 있다(반대 방향).

        새 UUID가 아니라 같은 `_USER`로 재야 한다 — 카테고리가 공유되면 generate의 히트 2건이
        write 버킷에 쌓여, 한도 1인 이 검사가 거부된다.
        """
        client = _client(_settings(user=2))
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200
        assert client.post(_PATH, json=_PAYLOAD).status_code == 429

        assert self._hit_user("write", times=1, limit=1) is True


# ══════════════════════════════════════════════════════════════════════════
# 3) 인증과의 관계 — 인증은 그대로, 리미터는 인증 뒤에서만 계수
# ══════════════════════════════════════════════════════════════════════════
class TestAuthRelationship:
    def test_unauthenticated_requests_are_401_and_do_not_consume_the_bucket(self) -> None:
        """무인증은 429가 아니라 401이고, IP 버킷을 소모하지 않는다.

        IP 한도 1로 걸고 무인증 3건을 보낸 뒤 인증 요청이 **200**이어야 한다. 리미터가 인증
        *앞에서* 계수하는 회귀라면 무인증 3건이 IP 버킷을 먼저 채워 이 요청이 429가 된다.
        """
        settings = _settings(ip=1)
        app = _app(settings)
        client = TestClient(app)

        for _ in range(3):
            assert client.post(_PATH, json=_PAYLOAD).status_code == 401

        app.dependency_overrides[get_current_user] = lambda: _USER
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200

    def test_minor_without_parental_consent_is_not_newly_blocked(self) -> None:
        """리미터 부착이 동의 게이트(SEC-20 D9)를 새로 만들지 않는다 — 접근 의미 불변.

        학부모 동의 없는 미성년자는 `ConsentedUser`였다면 403이다. `/v1/generate`의 게이트는
        SEC-07이 정한 `CurrentUser`(인증만)이므로 SEC-19 이후에도 200이어야 한다. 이 단정이
        깨지면 리미터가 `ConsentedUser`에 묶인 것이다(한도 부착과 동의 정책은 별개 결정).
        """
        minor = UserProfile(user_id=uuid.uuid4(), is_minor=True, parent_consent_at=None)
        client = _client(_settings(user=5), user=minor)

        assert client.post(_PATH, json=_PAYLOAD).status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 4) 배선 · 기본값
# ══════════════════════════════════════════════════════════════════════════
class TestWiringAndDefaults:
    def test_route_declares_the_generate_rate_limit_dependency(self) -> None:
        """POST /v1/generate 라우트가 `rate_limit_generate`를 의존성으로 선언한다(라우트 표 직독)."""
        app = _app(_settings(user=2))
        routes = [
            r
            for r in app.routes
            if isinstance(r, APIRoute) and r.path == _PATH and "POST" in r.methods
        ]

        assert len(routes) == 1  # 스캔 0건 = 공허 통과 방지
        assert any(dep.dependency is rate_limit_generate for dep in routes[0].dependencies)

    def test_default_settings_keep_the_limiter_active(self) -> None:
        """기본값이 세 차원 모두 양수 — 설정을 안 건드린 배포가 '무제한'으로 돌아가지 않는다."""
        settings = Settings(jwt_secret_key=SecretStr("test-secret-0123456789abcdef"))

        assert settings.generate_rate_limit_per_minute > 0
        assert settings.generate_rate_limit_ip_per_minute > 0
        assert settings.generate_rate_limit_device_per_minute > 0
        # 공유 NAT 방어 — IP 한도는 사용자 한도 이상이어야 한다(시각화 선례와 같은 위계).
        assert settings.generate_rate_limit_ip_per_minute >= settings.generate_rate_limit_per_minute


# ══════════════════════════════════════════════════════════════════════════
# 5) Redis 장애 — 기존 fail-safe(인메모리 폴백) 거동 유지
# ══════════════════════════════════════════════════════════════════════════
class RedisOutageError(RuntimeError):
    """폭발용 커스텀 예외 — 프로덕션 코드에 없는 이름이라 '진짜 장애가 흡수됐다'의 증거가 된다."""


class _DeadRedis:
    """모든 Redis 접근이 폭발 — 완전 장애 재현(`_RedisClient` 구조 충족)."""

    async def evalsha(self, sha: str, numkeys: int, *args: Any) -> Any:
        raise RedisOutageError("redis evalsha 폭발")

    async def script_load(self, script: str) -> str:
        raise RedisOutageError("redis script_load 폭발")

    async def ping(self) -> bool:
        raise RedisOutageError("redis ping 폭발")

    async def delete(self, *names: str) -> int:
        raise RedisOutageError("redis delete 폭발")

    async def keys(self, pattern: str) -> list[str]:
        raise RedisOutageError("redis keys 폭발")


class TestRedisOutage:
    def test_outage_degrades_to_inmemory_and_still_enforces(self) -> None:
        """Redis가 죽어도 `/v1/generate`는 500이 아니고, 한도도 **풀리지 않는다**(fail-open 아님).

        - 500이면 fail-closed 회귀(예외가 학생 대면 요청까지 샌다).
        - 3번째가 200이면 fail-open 회귀(장애 중 LLM 비용 방어가 사라진다).
        """
        counter = DegradationCounter("테스트")
        set_backend(RedisBackend(client=_DeadRedis(), degradation=counter))
        client = _client(_settings(user=2))

        assert client.post(_PATH, json=_PAYLOAD).status_code == 200
        assert client.post(_PATH, json=_PAYLOAD).status_code == 200
        assert client.post(_PATH, json=_PAYLOAD).status_code == 429
        assert counter.snapshot().failures_for("hit_many") == 3
