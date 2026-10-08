"""Sliding window rate limiter — L4 코치 엔드포인트 사용자당 분당 상한.

**백엔드 2종**(`Settings.coach_rate_limit_backend`로 선택):
- `"memory"` (기본): 단일 프로세스 인메모리 deque. 사이드카·로컬·테스트.
- `"redis"`: Redis 정렬 집합(ZSET) + Lua 원자성. **분산/HA 환경 정합** — 다중 워커·
  다중 인스턴스에서 사용자당 카운트가 *전역* 공유. `l3/cache/redis_cache.py`의 lazy
  + 주입 가능(`_RedisClient` Protocol) 패턴 답습. **Redis 장애 시 인메모리로 폴백**
  (OPS-06 — fail-open도 fail-closed도 아닌 제3의 길, `RedisBackend` 위 블록 주석 참조).

**경계**:
- 키 = `user_id`(인증된 사용자 단위). IP·세션 단위는 후속(미인증 표면 노출 시).
- 시계 = `time.monotonic()`(단조 — DST·NTP 조정 무관)·Redis 백엔드도 동일 시계 사용해
  *프로세스 간 시계 차이는 무관*(각 워커가 자기 시계로 ZADD; ±수ms 정합 충분).
- 동시성 = 인메모리는 FastAPI 단일 이벤트 루프 + GIL로 충분. **Redis는 Lua 스크립트로
  원자성 보장**(ZREMRANGEBYSCORE → ZCARD → ZADD/EXPIRE 한 트랜잭션).
- 미성년 PII 정합: 키는 UUID, 값은 타임스탬프 + UUID 토큰만(학생 발화 내용 0).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import (
    Annotated,
    Any,
    Literal,
    NamedTuple,
    Protocol,
    TypeVar,
    cast,
    runtime_checkable,
)

from fastapi import Depends, Request, Response

from whymath_backend.api._auth import ConsentedUser
from whymath_backend.api._degradation import DegradationCounter, DegradationSnapshot
from whymath_backend.api._device_metrics import record_device_sig_failure
from whymath_backend.api._device_store import get_device_store
from whymath_backend.api._error_codes import CodedHTTPException
from whymath_backend.config import Settings, get_settings

# redis-py의 NoScriptError를 지연 import — 라이브러리 미설치 환경(CI 단위테스트)에서도
# 모듈 import가 깨지지 않게 한다(`_build_default_redis_client` 패턴 정합). 미설치 환경
# 에서는 RedisBackend 자체가 사용되지 않으므로 fallback 클래스는 실제로 raise되지 않는다.
try:
    from redis.exceptions import NoScriptError
except ImportError:  # pragma: no cover — 라이브러리 미설치 환경

    class NoScriptError(Exception):  # type: ignore[no-redef]
        """fallback — redis 라이브러리 미설치 시 미사용 placeholder."""


_WINDOW_SECONDS = 60.0

# 폴백 반환 타입 — `_degrade_to_fallback`가 hit/hit_both/hit_many의 서로 다른 반환형을
# 그대로 통과시키기 위한 제네릭(코드베이스 관행: PEP 695 대신 명시 TypeVar — api/me.py 선례).
_FallbackT = TypeVar("_FallbackT")

RateCategory = Literal["read", "write", "device_register", "visualization", "auth", "defect_report"]
"""POST/GET 차등 한도 — 읽기/쓰기 분리 버킷(상호 영향 차단).

`device_register`(슬라이스 25): `/v1/devices/register`의 *전용* 버킷. coach `write`와 키 공간
분리 — 한쪽 폭주가 다른 쪽 한도를 잠식하지 않는다(예: coach 글 쓰기 폭주가 register를 막거나
그 반대). 등록은 *드문* 작업(첫 실행 1회·기기 변경)이라 낮은 한도(5/min user·10/min IP).

`visualization`(슬라이스 97): `/v1/visualizations/weak-concept`의 *전용* 버킷. coach `write`와
분리 — LLM 생성(비용)이라 더 낮은 한도(15/min user). coach는 프롬프트 결정만(LLM 미호출).

`auth`(SEC-08): `/v1/auth/{provider}/callback`·`/v1/auth/refresh`의 *IP 단위 전용* 버킷 —
둘 다 미인증 표면(로그인 남용·크리덴셜 스터핑 방어)이라 사용자 키가 없다. 콜백과 리프레시가
같은 카테고리를 공유하되(같은 IP의 두 엔드포인트 호출이 한 슬라이딩 윈도우를 나눠 쓴다) 각자
다른 한도(`auth_rate_limit_ip_per_minute`/`auth_rate_limit_ip_refresh_per_minute`)로 검사한다
— coach `write`·`device_register` 등 인증 표면과는 키 공간 분리(상호 영향 0).

`defect_report`(RPT-01): `POST /v1/reports/defects`의 *IP 단위 전용* 버킷 — 결함 신고는
`user_id`를 저장하지 않는(RPT-01 설계) *무인증* 표면이라 IP만 가능. coach `write`와 같은
"write" 카테고리를 공유하면 같은 IP에서의 coach 쓰기 폭주가 결함 신고 한도를 잠식하거나(또는
그 반대) 두 트래픽 패턴(LLM 대화 vs 1회성 신고)이 뒤섞여 어느 쪽 남용인지 구분이 안 되므로
`device_register`/`visualization` 선례처럼 전용 카테고리로 분리한다."""


class RateLimitResult(NamedTuple):
    """`hit()` 반환 — 허용 여부 + 클라이언트 throttle 정보(X-RateLimit-* 헤더 입력).

    - `allowed`: 한도 내면 True(요청 기록됨), 초과면 False(요청 미기록).
    - `remaining`: 이 호출 후 *남은 슬롯* 수(0 이상). 거부 시 0.
    - `reset_seconds`: 가장 오래된 항목이 만료되어 슬롯이 *하나 더 비기까지* 남은 초.
      윈도우가 비어있으면 0(즉시 사용 가능 — 첫 요청). 거부 시에도 의미 있음.
    """

    allowed: bool
    remaining: int
    reset_seconds: int


class CombinedRateLimitResult(NamedTuple):
    """`hit_both()` 반환 — user + IP 원자 동시 검사 결과(슬라이스 18).

    `allowed`는 둘 다 통과해야 True. 한쪽이라도 거부면 *어느 쪽도 미증가*(원자성). 개별
    `user_result`/`ip_result`는 *동일 atomic 결과*를 공유 — 둘 다 .allowed=False(거부) 또는
    둘 다 .allowed=True(통과). 한쪽이 None이면 해당 한도 미적용(limit=0 또는 ip 미상).
    """

    allowed: bool
    user_result: RateLimitResult | None
    ip_result: RateLimitResult | None


SubjectKind = Literal["user", "ip", "device"]
"""차원 식별자(슬라이스 20) — `hit_many` 일반화 입력. 추가 차원은 enum 확장으로 도입."""


class Subject(NamedTuple):
    """한 차원의 rate limit 검사 단위 — kind·id·limit. `hit_many` 입력 원소."""

    kind: SubjectKind
    id: str
    limit: int


@runtime_checkable
class RateLimitBackend(Protocol):
    """rate limit 백엔드 — sliding window 카운트의 저장·검사 추상.

    `category`(`"read"`/`"write"`)로 별도 버킷 — 한 카테고리 소진이 다른 카테고리에
    영향 주지 않는다(읽기 폭주가 쓰기를 막거나, 그 반대 차단). 슬라이스 16: `hit_by_ip`로
    IP 단위 한도(미인증 표면)도 같은 backend로 처리 — 사용자 키와 IP 키는 *네임스페이스
    분리*되어 충돌 없음(`user:<uid>` vs `ip:<addr>` 접두).
    """

    async def hit(
        self,
        user_id: uuid.UUID,
        *,
        category: RateCategory,
        limit: int,
        now: float,
    ) -> RateLimitResult:
        """*사용자 단위* 요청 기록 시도 — `RateLimitResult` 반환."""
        ...

    async def hit_by_ip(
        self,
        ip: str,
        *,
        category: RateCategory,
        limit: int,
        now: float,
    ) -> RateLimitResult:
        """*IP 단위* 요청 기록 시도 — 미인증 표면용. `RateLimitResult` 반환."""
        ...

    async def hit_both(
        self,
        user_id: uuid.UUID,
        ip: str | None,
        *,
        category: RateCategory,
        user_limit: int,
        ip_limit: int,
        now: float,
    ) -> CombinedRateLimitResult:
        """*원자적* user + IP 동시 검사 — 둘 다 통과해야 둘 다 increment(슬라이스 18).

        race window 0(인메모리는 단일 GIL 프레임·Redis는 단일 Lua 스크립트). 한쪽 limit=0
        또는 ip=None이면 해당 검사 비활성(`user_result`/`ip_result`는 None).
        """
        ...

    async def hit_many(
        self,
        subjects: list[Subject],
        *,
        category: RateCategory,
        now: float,
    ) -> dict[SubjectKind, RateLimitResult]:
        """*원자적* N-차원 동시 검사 — *전부* 통과해야 *전부* increment(슬라이스 20).

        하나라도 거부면 어느 차원도 미증가. 반환: kind → RateLimitResult(검사된 차원만).
        빈 리스트면 빈 dict(no-op). 한 kind가 중복되면 마지막이 우선(호출자 책임).
        """
        ...

    async def reset(self) -> None:
        """모든 카테고리·모든 카운트 초기화 — 테스트 격리용. production 미호출."""
        ...


def _result_from_window(
    *,
    allowed: bool,
    count_after: int,
    limit: int,
    oldest_ts: float | None,
    now: float,
) -> RateLimitResult:
    """sliding window 상태에서 표준 결과 객체 구성 — 인메모리·Redis 백엔드 공통.

    `allowed`는 호출자가 *명시*한다(`count_after ≤ limit`만으로는 *at-limit 미추가* 케이스를
    구분 못 함 — bucket이 limit로 가득 차고 추가 안 한 경우와 추가 후 limit 도달이 같은
    `count_after`로 보이기 때문).
    """
    remaining = max(0, limit - count_after)
    if (
        oldest_ts is None
    ):  # pragma: no cover — 정상 경로는 항상 oldest 존재(at-limit 시 bucket 비공)
        reset_seconds = 0
    else:
        reset_seconds = max(0, math.ceil(_WINDOW_SECONDS - (now - oldest_ts)))
    return RateLimitResult(allowed=allowed, remaining=remaining, reset_seconds=reset_seconds)


class InMemoryBackend:
    """프로세스-로컬 deque per (subject_key, category) — 단일 인스턴스 한정.

    `subject_key`는 `f"user:{uid}"` 또는 `f"ip:{addr}"` 접두로 네임스페이스 분리. 분산
    환경에서는 워커별 별도 카운트 → 효과 ÷ N. 그 경우 `RedisBackend` 사용.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], deque[float]] = {}

    async def _hit_by_key(
        self, subject_key: str, *, category: RateCategory, limit: int, now: float
    ) -> RateLimitResult:
        cutoff = now - _WINDOW_SECONDS
        bucket = self._by_key.setdefault((subject_key, category), deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        allowed = len(bucket) < limit
        if allowed:
            bucket.append(now)
        oldest = bucket[0] if bucket else None
        return _result_from_window(
            allowed=allowed,
            count_after=len(bucket),
            limit=limit,
            oldest_ts=oldest,
            now=now,
        )

    async def hit(
        self,
        user_id: uuid.UUID,
        *,
        category: RateCategory,
        limit: int,
        now: float,
    ) -> RateLimitResult:
        return await self._hit_by_key(f"user:{user_id}", category=category, limit=limit, now=now)

    async def hit_by_ip(
        self, ip: str, *, category: RateCategory, limit: int, now: float
    ) -> RateLimitResult:
        return await self._hit_by_key(f"ip:{ip}", category=category, limit=limit, now=now)

    async def hit_both(
        self,
        user_id: uuid.UUID,
        ip: str | None,
        *,
        category: RateCategory,
        user_limit: int,
        ip_limit: int,
        now: float,
    ) -> CombinedRateLimitResult:
        cutoff = now - _WINDOW_SECONDS
        user_bucket = (
            self._by_key.setdefault((f"user:{user_id}", category), deque())
            if user_limit > 0
            else None
        )
        ip_bucket = (
            self._by_key.setdefault((f"ip:{ip}", category), deque())
            if ip is not None and ip_limit > 0
            else None
        )
        # 두 버킷 모두 prune
        for bucket in (user_bucket, ip_bucket):
            if bucket is not None:
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
        # 원자 결정: 둘 다 슬롯이 있어야 추가
        user_ok = user_bucket is None or len(user_bucket) < user_limit
        ip_ok = ip_bucket is None or len(ip_bucket) < ip_limit
        atomic = user_ok and ip_ok
        if atomic:
            if user_bucket is not None:
                user_bucket.append(now)
            if ip_bucket is not None:
                ip_bucket.append(now)
        # 결과 구성 — 둘 다 *동일* atomic 결정 공유
        user_result = (
            _result_from_window(
                allowed=atomic,
                count_after=len(user_bucket),
                limit=user_limit,
                oldest_ts=user_bucket[0] if user_bucket else None,
                now=now,
            )
            if user_bucket is not None
            else None
        )
        ip_result = (
            _result_from_window(
                allowed=atomic,
                count_after=len(ip_bucket),
                limit=ip_limit,
                oldest_ts=ip_bucket[0] if ip_bucket else None,
                now=now,
            )
            if ip_bucket is not None
            else None
        )
        return CombinedRateLimitResult(allowed=atomic, user_result=user_result, ip_result=ip_result)

    async def hit_many(
        self,
        subjects: list[Subject],
        *,
        category: RateCategory,
        now: float,
    ) -> dict[SubjectKind, RateLimitResult]:
        if not subjects:
            return {}
        cutoff = now - _WINDOW_SECONDS
        # 각 subject별 (bucket, limit) 매핑 — 한 kind당 한 번만(중복은 마지막 우선)
        per_subject: list[tuple[Subject, deque[float]]] = []
        for s in subjects:
            bucket = self._by_key.setdefault((f"{s.kind}:{s.id}", category), deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            per_subject.append((s, bucket))
        atomic = all(len(b) < s.limit for s, b in per_subject)
        if atomic:
            for _s, bucket in per_subject:
                bucket.append(now)
        results: dict[SubjectKind, RateLimitResult] = {}
        for s, bucket in per_subject:
            oldest = bucket[0] if bucket else None
            results[s.kind] = _result_from_window(
                allowed=atomic,
                count_after=len(bucket),
                limit=s.limit,
                oldest_ts=oldest,
                now=now,
            )
        return results

    async def reset(self) -> None:
        self._by_key.clear()


# Redis 클라이언트 추상화 — l3/cache/redis_cache.py `_RedisClient` 패턴 답습.
# 우리가 실제로 쓰는 메서드만 좁게 선언(evalsha·script_load·eval 폴백·ping·delete·keys).
@runtime_checkable
class _RedisClient(Protocol):
    async def evalsha(self, sha: str, numkeys: int, *args: Any) -> Any:
        """EVALSHA — 캐시된 Lua 스크립트 실행(스크립트 SHA1 기준)."""
        ...

    async def script_load(self, script: str) -> Any:
        """SCRIPT LOAD — Lua 스크립트를 Redis 캐시에 적재, SHA1 반환."""
        ...

    async def ping(self) -> Any:
        """연결 도달성 확인."""
        ...

    async def delete(self, *names: str) -> Any:
        """키 삭제 — 테스트 reset용."""
        ...

    async def keys(self, pattern: str) -> Any:
        """패턴 매칭 키 목록 — 테스트 reset 보조."""
        ...


# Lua 스크립트 — *원자성* 핵심. ZREMRANGEBYSCORE → ZCARD → 조건부 ZADD/EXPIRE를
# 한 명령으로 묶어 race window 0. `now` 동일 타임스탬프 충돌 대비 멤버는 `now:uuid`.
# 반환 = {count_after, oldest_score_int_micros}. 백엔드가 RateLimitResult로 변환.
# (oldest는 micros 정수로 직렬화 — Redis Lua의 정수 반환 제약 + Python float 복원.)
_LUA_HIT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local cutoff = now - 60
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
local allowed = 0
if count < limit then
    redis.call('ZADD', key, now, ARGV[3])
    redis.call('EXPIRE', key, 60)
    count = count + 1
    allowed = 1
end
local oldest_micros = -1
local oldest_range = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if #oldest_range >= 2 then
    oldest_micros = math.floor(tonumber(oldest_range[2]) * 1000000)
end
return {allowed, count, oldest_micros}
"""

# 결정론적 SHA1 — 모듈 로드 시 1회 계산. Redis의 SCRIPT LOAD 결과(40-char hex)와 *정확히
# 일치*해야 EVALSHA가 캐시 적중한다(Redis는 같은 알고리즘 사용).
_LUA_HIT_SHA1 = hashlib.sha1(_LUA_HIT.encode("utf-8")).hexdigest()


# 슬라이스 18 — 원자적 user + IP 동시 검사. 두 키를 한 Lua 트랜잭션에서 검사·필요시 둘 다
# 증가. 한 쪽이라도 거부면 *어느 쪽도 미증가*(낭비 counter 0·race window 0).
# 한쪽 limit=0이면 그쪽 검사·증가 *모두* 스킵(키 미터치). 반환:
#   {allowed, user_count_after, user_oldest_micros, ip_count_after, ip_oldest_micros}
# 미사용 쪽은 count=-1·oldest=-1 sentinel(Python이 None으로 매핑).
_LUA_HIT_BOTH = """
local user_key = KEYS[1]
local ip_key = KEYS[2]
local now = tonumber(ARGV[1])
local user_limit = tonumber(ARGV[2])
local ip_limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now - 60
local user_count = -1
local ip_count = -1
local user_ok = 1
local ip_ok = 1
if user_limit > 0 then
    redis.call('ZREMRANGEBYSCORE', user_key, '-inf', cutoff)
    user_count = redis.call('ZCARD', user_key)
    if user_count >= user_limit then user_ok = 0 end
end
if ip_limit > 0 then
    redis.call('ZREMRANGEBYSCORE', ip_key, '-inf', cutoff)
    ip_count = redis.call('ZCARD', ip_key)
    if ip_count >= ip_limit then ip_ok = 0 end
end
local allowed = 0
if user_ok == 1 and ip_ok == 1 then
    allowed = 1
    if user_limit > 0 then
        redis.call('ZADD', user_key, now, member)
        redis.call('EXPIRE', user_key, 60)
        user_count = user_count + 1
    end
    if ip_limit > 0 then
        redis.call('ZADD', ip_key, now, member)
        redis.call('EXPIRE', ip_key, 60)
        ip_count = ip_count + 1
    end
end
local user_oldest = -1
local ip_oldest = -1
if user_limit > 0 then
    local r = redis.call('ZRANGE', user_key, 0, 0, 'WITHSCORES')
    if #r >= 2 then user_oldest = math.floor(tonumber(r[2]) * 1000000) end
end
if ip_limit > 0 then
    local r = redis.call('ZRANGE', ip_key, 0, 0, 'WITHSCORES')
    if #r >= 2 then ip_oldest = math.floor(tonumber(r[2]) * 1000000) end
end
return {allowed, user_count, user_oldest, ip_count, ip_oldest}
"""
_LUA_HIT_BOTH_SHA1 = hashlib.sha1(_LUA_HIT_BOTH.encode("utf-8")).hexdigest()


# 슬라이스 20 — N차원 일반화 원자 검사. KEYS는 가변, ARGV는 [now, member, limit1, ..., limitN].
# 반환: [allowed, count1, oldest1, count2, oldest2, ..., countN, oldestN].
# 차원 N=2면 _LUA_HIT_BOTH와 의미 동등(향후 hit_both 폐기 후보).
_LUA_HIT_MANY = """
local now = tonumber(ARGV[1])
local member = ARGV[2]
local cutoff = now - 60
local n = #KEYS
-- Prune 전부
for i = 1, n do
    redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', cutoff)
end
-- 카운트 + 한도 검사
local counts = {}
local all_ok = 1
for i = 1, n do
    local limit = tonumber(ARGV[2 + i])
    local count = redis.call('ZCARD', KEYS[i])
    counts[i] = count
    if count >= limit then all_ok = 0 end
end
-- 전부 OK면 전부 ZADD
if all_ok == 1 then
    for i = 1, n do
        redis.call('ZADD', KEYS[i], now, member)
        redis.call('EXPIRE', KEYS[i], 60)
        counts[i] = counts[i] + 1
    end
end
-- 응답 조립: [allowed, count1, oldest1, count2, oldest2, ...]
local response = {all_ok}
for i = 1, n do
    table.insert(response, counts[i])
    local r = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
    local oldest = -1
    if #r >= 2 then oldest = math.floor(tonumber(r[2]) * 1000000) end
    table.insert(response, oldest)
end
return response
"""
_LUA_HIT_MANY_SHA1 = hashlib.sha1(_LUA_HIT_MANY.encode("utf-8")).hexdigest()


def _build_default_redis_client(settings: Settings) -> _RedisClient:
    """기본 redis.asyncio 클라이언트 — 지연 import(라이브러리 없는 환경 보호).

    Redis 연결 자체는 라이브 통합 테스트(@integration·실 Redis 데몬)에서 검증한다 —
    hermetic 테스트는 `client=`로 가짜 주입(테스트 패턴 정합). 다만 **소켓 타임아웃 결선은
    hermetic으로도 검증한다**(실물 `redis.asyncio.Redis`의 `connection_pool.connection_kwargs`
    확인 — 네트워크는 타지 않는다). CLAUDE.md: 외부 SDK 표면을 시임만으로 정합 선언 금지.

    **소켓 타임아웃을 명시한다** (OPS-06 — OPS-05가 L3 캐시에 건 것과 같은 축): rate limit는
    *모든* 코치 요청의 앞단이라 여기서 매달리면 서비스 전체가 매달린다. 인자를 주지 않으면
    값이 라이브러리 버전 기본값에 종속된다(설치본 redis-py 8.0.1 실측 5초). 응답 대기
    (`socket_timeout`)와 연결 수립(`socket_connect_timeout`) 둘 다 건다 — 하나만 걸면 나머지
    축에서 무한 대기가 그대로 남는다.
    """
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        raise RuntimeError(
            "redis Python 클라이언트가 설치되지 않았습니다. "
            "`pip install redis[hiredis]` 후 다시 시도하세요."
        ) from exc
    timeout_s = settings.redis_socket_timeout_s
    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=timeout_s,
        socket_connect_timeout=timeout_s,
    )
    return cast(_RedisClient, client)


# ──────────────────────────────────────────────────────────────────────────
# OPS-06 — Redis 장애 시 rate limit 강등: **제3의 길(인메모리 폴백)**
#
# 두 흔한 선택지는 둘 다 우리 우선순위를 어긴다:
#   - **fail-open**(무제한 통과): 한도가 사라져 남용·LLM 비용 폭주에 무방비. 게다가 rate limit는
#     `_client_device_id`를 거쳐 디바이스 서명 검증과 같은 경로에 있다 — 방어선을 통째로 여는 셈.
#   - **fail-closed**(전 요청 429/5xx): Redis 하나 죽었다고 *모든 학생*이 학습을 못 한다.
#     CLAUDE.md 우선순위 #1(학생 안전·웰빙)의 정면 위반이고, 캐시 장애를 학생 대면 실패로
#     번지게 하지 말라는 OPS-05의 결론과도 반대다.
#
# 그래서 같은 모듈의 `InMemoryBackend`로 **폴백**한다. 한도는 계속 걸리되(무제한 아님) 계수가
# 워커별로 갈라져 *분산 정확도*가 떨어진다 — N워커면 실효 한도가 최대 N배까지 느슨해질 수
# 있다. 이것이 이 설계가 지불하는 정확한 대가다(유계 완화 ≠ 무제한).
#
# 그 밖의 트레이드오프(정직하게):
#   - 폴백 버킷은 장애 *시작 시점에 비어 있다* — 진행 중이던 창의 이력이 승계되지 않아 그
#     순간 한도가 한 번 리셋된 것처럼 보인다.
#   - Redis 회복 후에는 다시 Redis 계수로 돌아가며, 장애 중 인메모리에 쌓인 히트는 Redis
#     카운트에 반영되지 않는다(반대 방향도 마찬가지). 두 회계는 합쳐지지 않는다.
#   - 폴백 발동은 반드시 *관측 가능*해야 한다 — 예외 타입명 로그 + 인프로세스 카운터.
#     그래야 "조용히 느슨해진 채로 몇 주"가 생기지 않는다(침묵 실패 금지).
# ──────────────────────────────────────────────────────────────────────────

# 강등 회계의 연산 어휘 — 로그·스냅샷·테스트가 공유하는 단일 상수.
RATE_LIMIT_OP_HIT = "hit"
RATE_LIMIT_OP_HIT_BOTH = "hit_both"
RATE_LIMIT_OP_HIT_MANY = "hit_many"

_RATE_LIMIT_EFFECT = (
    "인메모리 백엔드로 폴백합니다 — 한도는 계속 적용되나(무제한 아님) "
    "계수가 워커별로 갈라져 분산 정확도가 떨어집니다."
)

# 프로세스 전역 회계 — 백엔드 인스턴스가 교체돼도 "이 프로세스가 Redis 없이 버틴 횟수"는
# 하나로 합산돼야 운영 판정이 된다(OPS-05 `_PROCESS_DEGRADATION` 선례).
_PROCESS_DEGRADATION = DegradationCounter("rate limit")


def rate_limit_degradation_snapshot() -> DegradationSnapshot:
    """프로세스 전역 rate limit 강등 회계 스냅샷 — 운영 노출·진단의 읽기 표면.

    관측 SaaS가 죽어도 남는 인프로세스 판정치(이중 회계). `total_failures > 0`이면 그동안의
    한도는 *분산 정확도가 보장되지 않는다*고 읽어야 한다.
    """
    return _PROCESS_DEGRADATION.snapshot()


def reset_rate_limit_degradation() -> None:
    """프로세스 전역 회계 초기화 — 테스트 격리용."""
    _PROCESS_DEGRADATION.reset()


class RedisBackend:
    """Redis ZSET sliding window — 분산/HA 정합 + EVALSHA 최적화.

    Lua 스크립트 `_LUA_HIT`가 ZREMRANGEBYSCORE→ZCARD→조건부 ZADD/EXPIRE를 원자로
    수행해 race window 0. 키 prefix `rate:coach:` + user_id(UUID). 60초 TTL 자동 만료로
    유휴 사용자 키 누수 방지.

    **EVALSHA 최적화**(슬라이스 13): EVAL 대신 EVALSHA(SHA1) 사용 — 매 호출 풀 스크립트
    바이트 전송 회피(분산 환경 네트워크·Redis 파싱 비용 절감). `_LUA_HIT_SHA1`은 모듈 로드
    시 결정론적으로 계산되며, Redis SCRIPT LOAD 결과와 *반드시 일치*한다(같은 SHA1 알고리즘).
    `NoScriptError`(SCRIPT FLUSH·Redis 재시작 등으로 캐시에서 사라진 경우) 시 한 번
    `script_load` + 재시도. 정상 경로는 EVALSHA 1회.

    **장애 폴백(OPS-06)**: Redis 접근이 실패하면 예외를 올려 보내지 않고 내장
    `InMemoryBackend`로 폴백한다 — 근거·트레이드오프는 이 클래스 바로 위의 블록 주석 참조.
    `NoScriptError` 처리는 폴백이 아니라 *정상 동작의 일부*라 종전 그대로다(스크립트 재적재
    후 재시도). 폴백은 그 재시도까지 실패했을 때만 발동한다.

    가드를 데코레이터가 아니라 **이 클래스 안**에 두는 이유: OPS-05가 세운 "네트워크 실패의
    *발원지*에서 한 번에 막는다" 원칙이다. 래퍼로 두면 `configure_backend_from_settings`를
    거치지 않고 `RedisBackend(...)`를 직접 만든 경로(테스트·스크립트·후속 코드)가 무방비로
    남는다 — 보호가 조립 방식에 의존하면 언젠가 빠진다.
    """

    _KEY_PREFIX = "rate:coach:"

    def __init__(
        self,
        *,
        client: _RedisClient | None = None,
        settings: Settings | None = None,
        fallback: InMemoryBackend | None = None,
        degradation: DegradationCounter | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        # 폴백은 *즉시* 만들어 둔다(비용 = 빈 dict 하나). 장애 순간에 생성 실패할 여지를 없앤다.
        self._fallback = fallback if fallback is not None else InMemoryBackend()
        # 기본은 프로세스 전역 회계(인스턴스 교체와 무관) — 테스트는 새 카운터 주입.
        self._degradation = degradation if degradation is not None else _PROCESS_DEGRADATION

    @property
    def _resolved_settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_client(self) -> _RedisClient:
        if self._client is None:
            self._client = _build_default_redis_client(self._resolved_settings)
        return self._client

    def _key(self, subject_key: str, category: RateCategory) -> str:
        # 카테고리·subject(user:/ip:)별 키 분리 — 예: `rate:coach:read:user:{uid}` /
        # `rate:coach:write:ip:{addr}`. 사용자·IP 네임스페이스 충돌 없음.
        return f"{self._KEY_PREFIX}{category}:{subject_key}"

    @property
    def degradation_count(self) -> int:
        """이 백엔드가 쓰는 회계의 누적 폴백 횟수 — 인프로세스 판정치."""
        return self._degradation.snapshot().total_failures

    def degradation_snapshot(self) -> DegradationSnapshot:
        """이 백엔드가 쓰는 회계의 불변 스냅샷(연산별 폴백·연속 실패·마지막 예외 타입)."""
        return self._degradation.snapshot()

    async def _evalsha_with_reload(self, sha: str, script: str, numkeys: int, *args: Any) -> Any:
        """EVALSHA + NOSCRIPT 자동 복구 — *정상 동작*의 일부(폴백 아님).

        SCRIPT FLUSH·Redis 재시작으로 스크립트 캐시가 비면 `NoScriptError`가 나는데, 이는
        장애가 아니라 예상된 상태 전이다. 한 번 `script_load` 후 재시도한다. 이 재시도까지
        실패하면 그때는 진짜 장애이므로 호출자의 폴백 가드가 받는다.
        """
        client = self._get_client()
        try:
            return await client.evalsha(sha, numkeys, *args)
        except NoScriptError:
            await client.script_load(script)
            return await client.evalsha(sha, numkeys, *args)

    async def _hit_by_key(
        self, subject_key: str, *, category: RateCategory, limit: int, now: float
    ) -> RateLimitResult:
        key = self._key(subject_key, category)
        unique_member = f"{now}:{uuid.uuid4().hex}"
        try:
            raw = await self._evalsha_with_reload(
                _LUA_HIT_SHA1, _LUA_HIT, 1, key, now, limit, unique_member
            )
            allowed = int(raw[0]) == 1
            count_after = int(raw[1])
            oldest_micros = int(raw[2])
        except Exception as exc:  # noqa: BLE001 — Redis 장애를 학생 대면 실패로 전파 금지
            # 응답 파싱까지 try 안에 두는 이유: 형태가 깨진 응답도 결국 "Redis를 못 쓰는
            # 상태"라 같은 폴백으로 다뤄야 학생 경로가 안 깨진다(OPS-05 `_decode` 선례).
            # `_hit_by_key`는 InMemoryBackend의 내부 표면이지만 *같은 모듈의 자매 구현*이라
            # 접근이 정당하다 — subject_key 접두(user:/ip:/device:) 규약을 두 백엔드가 공유하므로
            # 공개 메서드로 우회하면 접두를 두 번 붙이게 된다.
            return await self._degrade_to_fallback(
                RATE_LIMIT_OP_HIT,
                exc,
                lambda: self._fallback._hit_by_key(
                    subject_key, category=category, limit=limit, now=now
                ),
            )
        self._degradation.record_success()
        oldest_ts = None if oldest_micros < 0 else oldest_micros / 1_000_000
        return _result_from_window(
            allowed=allowed,
            count_after=count_after,
            limit=limit,
            oldest_ts=oldest_ts,
            now=now,
        )

    async def _degrade_to_fallback(
        self,
        operation: str,
        exc: BaseException,
        fallback_call: Callable[[], Awaitable[_FallbackT]],
    ) -> _FallbackT:
        """폴백 1건 — 회계·로그(예외 타입명)를 남기고 인메모리 백엔드로 넘긴다.

        키·사용자 ID·IP는 로그에 싣지 않는다(미성년자 PII 인접 표면). 남는 것은 *연산명·예외
        타입명·횟수*뿐이며, 그것만으로 "지금 한도가 워커별로 갈라져 있다"는 판정이 선다.
        """
        self._degradation.record_failure(operation, exc, effect=_RATE_LIMIT_EFFECT)
        return await fallback_call()

    async def hit(
        self,
        user_id: uuid.UUID,
        *,
        category: RateCategory,
        limit: int,
        now: float,
    ) -> RateLimitResult:
        return await self._hit_by_key(f"user:{user_id}", category=category, limit=limit, now=now)

    async def hit_by_ip(
        self, ip: str, *, category: RateCategory, limit: int, now: float
    ) -> RateLimitResult:
        return await self._hit_by_key(f"ip:{ip}", category=category, limit=limit, now=now)

    async def hit_both(
        self,
        user_id: uuid.UUID,
        ip: str | None,
        *,
        category: RateCategory,
        user_limit: int,
        ip_limit: int,
        now: float,
    ) -> CombinedRateLimitResult:
        """원자적 user+IP 검사 — 단일 Lua 스크립트로 둘 다 *함께* 결정.

        Redis MULTI 없이도 Lua가 원자성 보장. IP=None이면 ip_limit=0으로 강제(키 미터치).
        NoScriptError 재적재는 hit()과 동일 패턴이고, 그마저 실패하면 OPS-06 인메모리 폴백.
        """
        # IP 미상이면 IP 키도 의미 없음 — limit=0 강제로 Lua가 검사 스킵
        effective_ip_limit = ip_limit if ip is not None else 0
        user_key = self._key(f"user:{user_id}", category)
        ip_key = self._key(f"ip:{ip}", category) if ip is not None else "__unused__"
        member = f"{now}:{uuid.uuid4().hex}"
        try:
            raw = await self._evalsha_with_reload(
                _LUA_HIT_BOTH_SHA1,
                _LUA_HIT_BOTH,
                2,
                user_key,
                ip_key,
                now,
                user_limit,
                effective_ip_limit,
                member,
            )
            allowed = int(raw[0]) == 1
            user_count = int(raw[1])
            user_oldest_micros = int(raw[2])
            ip_count = int(raw[3])
            ip_oldest_micros = int(raw[4])
        except Exception as exc:  # noqa: BLE001 — Redis 장애를 학생 대면 실패로 전파 금지
            return await self._degrade_to_fallback(
                RATE_LIMIT_OP_HIT_BOTH,
                exc,
                lambda: self._fallback.hit_both(
                    user_id,
                    ip,
                    category=category,
                    user_limit=user_limit,
                    ip_limit=ip_limit,
                    now=now,
                ),
            )
        self._degradation.record_success()
        user_result = (
            _result_from_window(
                allowed=allowed,
                count_after=user_count,
                limit=user_limit,
                oldest_ts=None if user_oldest_micros < 0 else user_oldest_micros / 1_000_000,
                now=now,
            )
            if user_limit > 0
            else None
        )
        ip_result = (
            _result_from_window(
                allowed=allowed,
                count_after=ip_count,
                limit=effective_ip_limit,
                oldest_ts=None if ip_oldest_micros < 0 else ip_oldest_micros / 1_000_000,
                now=now,
            )
            if effective_ip_limit > 0
            else None
        )
        return CombinedRateLimitResult(
            allowed=allowed, user_result=user_result, ip_result=ip_result
        )

    async def hit_many(
        self,
        subjects: list[Subject],
        *,
        category: RateCategory,
        now: float,
    ) -> dict[SubjectKind, RateLimitResult]:
        """N-차원 원자 검사 — 단일 Lua `_LUA_HIT_MANY`로 모든 차원 함께 결정.

        학생 대면 코치 엔드포인트가 실제로 타는 경로(user+IP+device 3차원)라, OPS-06 폴백이
        가장 자주 발동할 지점이기도 하다.
        """
        if not subjects:
            return {}
        keys = [self._key(f"{s.kind}:{s.id}", category) for s in subjects]
        member = f"{now}:{uuid.uuid4().hex}"
        argv: list[float | int | str] = [now, member]
        argv.extend(s.limit for s in subjects)
        results: dict[SubjectKind, RateLimitResult] = {}
        try:
            raw = await self._evalsha_with_reload(
                _LUA_HIT_MANY_SHA1, _LUA_HIT_MANY, len(keys), *keys, *argv
            )
            allowed = int(raw[0]) == 1
            for i, s in enumerate(subjects):
                count_after = int(raw[1 + i * 2])
                oldest_micros = int(raw[2 + i * 2])
                oldest_ts = None if oldest_micros < 0 else oldest_micros / 1_000_000
                results[s.kind] = _result_from_window(
                    allowed=allowed,
                    count_after=count_after,
                    limit=s.limit,
                    oldest_ts=oldest_ts,
                    now=now,
                )
        except Exception as exc:  # noqa: BLE001 — Redis 장애를 학생 대면 실패로 전파 금지
            return await self._degrade_to_fallback(
                RATE_LIMIT_OP_HIT_MANY,
                exc,
                lambda: self._fallback.hit_many(subjects, category=category, now=now),
            )
        self._degradation.record_success()
        return results

    async def reset(self) -> None:
        """패턴 매칭 키 일괄 삭제 — 테스트 격리용. production 미호출.

        OPS-06: 폴백 버킷도 함께 비운다(둘 중 하나만 비면 테스트 격리가 새는데, 인메모리 쪽은
        장애 중에만 채워져 눈에 잘 안 띈다). Redis 쪽 실패는 **강등하지 않고 전파**한다 —
        이 메서드는 학생 경로가 아니라 테스트 도구이고, 여기서의 침묵은 "격리에 성공했다"는
        거짓 신호가 되어 다음 테스트를 오염시킨다.
        """
        await self._fallback.reset()
        client = self._get_client()
        keys = await client.keys(f"{self._KEY_PREFIX}*")
        if keys:
            await client.delete(*keys)


# 모듈 전역 — FastAPI 단일 프로세스 가정에서 backend 인스턴스 1개 재사용.
# 테스트는 `set_backend()`로 가짜 주입.
_BACKEND: RateLimitBackend = InMemoryBackend()


def set_backend(backend: RateLimitBackend) -> None:
    """전역 백엔드 교체 — 테스트·런타임 전환용."""
    global _BACKEND
    _BACKEND = backend


def get_backend() -> RateLimitBackend:
    """현재 백엔드 반환 — 테스트 단언용."""
    return _BACKEND


def configure_backend_from_settings(settings: Settings) -> None:
    """설정에 따라 백엔드 선택·설치. 앱 lifespan 시작 시 호출(또는 첫 사용 전)."""
    if settings.coach_rate_limit_backend == "redis":
        set_backend(RedisBackend(settings=settings))
    else:
        set_backend(InMemoryBackend())


async def reset_store() -> None:
    """테스트 격리용 — 현재 백엔드의 카운트 리셋. production 미호출."""
    await _BACKEND.reset()


def _rate_headers(limit: int, result: RateLimitResult) -> dict[str, str]:
    """표준 IETF 드래프트 RateLimit 헤더(GitHub-style 변형) — 클라이언트 자체 throttle 입력.

    - `X-RateLimit-Limit`: 윈도우당 최대 요청 수.
    - `X-RateLimit-Remaining`: *이 응답 시점* 남은 슬롯 수(0=다음 호출은 429 가능).
    - `X-RateLimit-Reset`: 다음 슬롯이 비기까지 *남은 초*(0=즉시 가능). 거부 시에도 의미.
    """
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset_seconds),
    }


def _pair_headers(prefix: str, limit: int, result: RateLimitResult) -> dict[str, str]:
    """차원별(`User`/`Ip`) 헤더 — Defense에서 두 쌍 동시 노출(슬라이스 19).

    `X-RateLimit-{prefix}-Limit/Remaining/Reset`. 클라이언트가 *어느 차원이 더 빠듯한지*
    독립적으로 인식 가능(rollup만으로는 가려진 다른 차원의 상태도 동시 노출).
    """
    return {
        f"X-RateLimit-{prefix}-Limit": str(limit),
        f"X-RateLimit-{prefix}-Remaining": str(result.remaining),
        f"X-RateLimit-{prefix}-Reset": str(result.reset_seconds),
    }


# 슬라이스 11-15의 user-only `rate_limit_read/write` 및 헬퍼 `_enforce`는 슬라이스 17의
# Defense(사용자+IP) 도입으로 *모두 대체*됨(clean cut). 호출자 0 — 죽은 코드 제거(CLAUDE.md
# "범위 밖 기능 금지"). 사용자 한도만 원하면 `ip_limit=0` 설정으로 Defense가 동등하게 동작.


def _client_ip(request: Request, *, settings: Settings) -> str | None:
    """요청에서 IP 추출 — 신뢰 프록시가 검증된 경우에만 `X-Forwarded-For`를 읽는다
    (SEC-24, 원 SEC-14).

    `request.client`가 None이면 항상 None 반환(회귀 없음 — 호출자는 한도 미적용으로 처리).

    프록시 신뢰 모델(우측-신뢰, 화이트리스트 기반): `X-Forwarded-For`는 각 홉이 *자신에게
    연결한 피어*를 오른쪽에 append하며 전달하는 관례라, `request.client.host`(우리 서버에
    직접 TCP 연결한 피어)는 헤더에 없고 헤더의 가장 오른쪽 값이 그 직전 홉이 본 피어다.

    1. `settings.trusted_proxy_ips`가 비어 있거나 `request.client.host`가 그 집합에 없으면
       → **X-Forwarded-For를 완전히 무시**하고 `request.client.host`를 그대로 반환(신뢰
       프록시가 구성되지 않은 배포의 기본 자세 — 클라이언트가 임의로 보낼 수 있는 헤더를
       신뢰하지 않으므로 위조로 rate limit·감사 IP를 속일 수 없다).
    2. `request.client.host`가 신뢰 프록시 목록에 있으면 → X-Forwarded-For를 콤마로 분리해
       *오른쪽부터* 순회, 신뢰 프록시 목록에 있는 값은 건너뛰고 처음 만나는 미신뢰 값을 원
       클라이언트 IP로 반환. 전부 신뢰 프록시이거나 헤더가 비어 있으면 `request.client.host`로
       안전 폴백(신뢰 체인은 확인됐으나 원 클라이언트를 특정할 근거가 없는 경우).

    IP 문자열은 `strip()`만 하고 그 외 정규화(CIDR 매칭·IPv6 압축 등)는 하지 않는다.
    """
    if request.client is None:
        return None
    direct_peer = request.client.host
    trusted = settings.trusted_proxy_ips
    if not trusted or direct_peer not in trusted:
        return direct_peer
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",")]
        for hop in reversed(hops):
            if hop and hop not in trusted:
                return hop
    return direct_peer


async def _enforce_by_ip(
    ip: str,
    *,
    category: RateCategory,
    limit: int,
    response: Response,
) -> None:
    """IP 단위 한도 검사. 사용자 한도와 동일 시맨틱(429 + 헤더). limit=0이면 비활성.

    슬라이스 19 — `X-RateLimit-Ip-*` 차원 헤더도 동시 노출(미인증 표면에선 user 차원 없음).
    """
    if limit == 0:
        return
    result = await _BACKEND.hit_by_ip(ip, category=category, limit=limit, now=time.monotonic())
    rollup = _rate_headers(limit, result)
    pair = _pair_headers("Ip", limit, result)
    if not result.allowed:
        raise CodedHTTPException(
            "WM-RATE-001",
            detail="요청이 너무 많습니다(분당 한도 초과). 잠시 후 다시 시도하세요.",
            headers={"Retry-After": str(result.reset_seconds or 60), **rollup, **pair},
        )
    for key, value in {**rollup, **pair}.items():
        response.headers[key] = value


async def rate_limit_ip_read(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """*IP 단위 읽기* 한도 — 미인증 GET 엔드포인트용. IP 추출 실패 시 적용 안 함."""
    ip = _client_ip(request, settings=settings)
    if ip is None:
        return
    await _enforce_by_ip(
        ip,
        category="read",
        limit=settings.coach_rate_limit_ip_read_per_minute,
        response=response,
    )


async def rate_limit_ip_write(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """*IP 단위 쓰기* 한도 — 미인증 POST 엔드포인트용. IP 추출 실패 시 적용 안 함."""
    ip = _client_ip(request, settings=settings)
    if ip is None:
        return
    await _enforce_by_ip(
        ip,
        category="write",
        limit=settings.coach_rate_limit_ip_write_per_minute,
        response=response,
    )


RateLimitedIpRead = Depends(rate_limit_ip_read)
"""*미인증* GET 엔드포인트용 의존성(IP 단위) — `dependencies=[RateLimitedIpRead]`."""

RateLimitedIpWrite = Depends(rate_limit_ip_write)
"""*미인증* POST 엔드포인트용 의존성(IP 단위) — `dependencies=[RateLimitedIpWrite]`."""


# ──────────────────────────────────────────────────────────────────────────
# RPT-01 — 학생 결함 신고(`POST /v1/reports/defects`) 전용 IP 단위 rate limit.
# coach write와 category 분리(모듈 docstring `defect_report` 항목 참조) — 저장 기반 방어
# 신설 없이(CLAUDE.md·태스크 명세) 기존 `_enforce_by_ip` 재사용만으로 남용을 방어한다.
# ──────────────────────────────────────────────────────────────────────────


async def rate_limit_ip_defect_report(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """결함 신고(`POST /v1/reports/defects`) 전용 *IP 단위* 한도. IP 추출 실패 시 적용 안 함.

    `user_id`를 저장하지 않는 무인증 표면이라 IP 차원만 가능(user·device 차원 N/A).
    """
    ip = _client_ip(request, settings=settings)
    if ip is None:
        return
    await _enforce_by_ip(
        ip,
        category="defect_report",
        limit=settings.defect_report_rate_limit_ip_per_minute,
        response=response,
    )


RateLimitedIpDefectReport = Depends(rate_limit_ip_defect_report)
"""결함 신고 전용(RPT-01) — `dependencies=[RateLimitedIpDefectReport]`."""


# ──────────────────────────────────────────────────────────────────────────
# SEC-08 — 인증 표면(`/v1/auth/{provider}/callback`·`/v1/auth/refresh`) IP 단위 한도.
# 재구현 0 — `_client_ip`+`_enforce_by_ip`(위 rate_limit_ip_read/write와 동일 패턴)만 재사용.
# 둘 다 미인증 표면(로그인 시도·리프레시 회전은 사용자 신원 확정 *전*이라 IP 키만 가능).
# ──────────────────────────────────────────────────────────────────────────


async def rate_limit_auth_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """OAuth 콜백(`/v1/auth/{provider}/callback`) IP 단위 한도 — 미인증 표면(로그인 남용 방어).

    IP 추출 실패 시 적용 안 함(기존 rate_limit_ip_* fail-safe와 동일 시맨틱). Redis 백엔드
    장애 시 `_enforce_by_ip`가 호출하는 `_BACKEND.hit_by_ip`가 OPS-06 인메모리 폴백을 그대로
    상속한다(이 함수는 재구현 0 — 기존 fail-safe 거동 유지).
    """
    ip = _client_ip(request, settings=settings)
    if ip is None:
        return
    await _enforce_by_ip(
        ip,
        category="auth",
        limit=settings.auth_rate_limit_ip_per_minute,
        response=response,
    )


async def rate_limit_auth_refresh(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """리프레시(`/v1/auth/refresh`) IP 단위 한도 — 미인증 표면.

    IP 추출 실패 시 적용 안 함. Redis 장애 시 OPS-06 인메모리 폴백 그대로 상속(재구현 0).
    """
    ip = _client_ip(request, settings=settings)
    if ip is None:
        return
    await _enforce_by_ip(
        ip,
        category="auth",
        limit=settings.auth_rate_limit_ip_refresh_per_minute,
        response=response,
    )


RateLimitedAuthCallback = Depends(rate_limit_auth_callback)
"""OAuth 콜백 전용(SEC-08) — `dependencies=[RateLimitedAuthCallback]`."""

RateLimitedAuthRefresh = Depends(rate_limit_auth_refresh)
"""리프레시 전용(SEC-08) — `dependencies=[RateLimitedAuthRefresh]`."""


# ──────────────────────────────────────────────────────────────────────────
# 슬라이스 20 — 3차원 한도(user+IP+device, X-Device-Id 헤더).
# ──────────────────────────────────────────────────────────────────────────


def _expected_device_signature(secret: str, device_id: str) -> str:
    """`HMAC-SHA256(secret, device_id)` 의 hex digest — 64-char lowercase."""
    return hmac.new(secret.encode("utf-8"), device_id.encode("utf-8"), hashlib.sha256).hexdigest()


async def _client_device_id(request: Request, settings: Settings) -> str | None:
    """요청에서 디바이스 ID 추출 — `X-Device-Id` 헤더(클라이언트 발급 UUID/문자열).

    빈 값/미설정 시 None — 디바이스 차원 검사 비활성. 클라이언트는 첫 실행 시 안정 ID
    (UUID4·KeyChain 저장)를 생성·전 요청에 동봉(Flutter `device_info_plus`·iOS
    `identifierForVendor`·Android `Settings.Secure.ANDROID_ID` 등 권장).

    **검증 경로 우선순위**(슬라이스 22 도입·23 async 전환):
    1. **디바이스별 store**(`set_device_store(store)`로 활성) — 등록된 device_id의 *고유*
       secret으로 X-Device-Sig 검증. slice 21 공유 secret 한계 해소(앱 바이너리 추출 시
       *그 디바이스만* 영향, 다른 디바이스 secret 무관). 정식 운영 경로(`PgDeviceStore`).
    2. **공유 HMAC secret**(`coach_device_hmac_secret`) — store 미설정 시 폴백. slice 21
       trivial-spoofing 방어. MVP/sandbox용·등록 인프라 없이 동작.
    3. **secret 미설정** — 서명 검증 생략(slice 20 동작·backward compat).

    누락·불일치 시 device_id를 None으로 *fail-safe* — device 차원 검사 비활성(요청 자체는
    통과·user+IP만 적용).

    슬라이스 23: store.verify가 async(PG 라운드트립)라 본 함수도 `async def`로 전환. 호출처
    (`_enforce_triple` → `rate_limit_triple_*`)는 이미 async — `await` 한 줄 추가뿐.
    """
    device_id = request.headers.get("x-device-id")
    if device_id is None:
        return None
    stripped = device_id.strip()
    if not stripped:
        return None
    store = get_device_store()
    if store is not None:
        # 디바이스별 store 모드(우선) — 등록된 device_id만 유효
        provided = request.headers.get("x-device-sig", "").strip()
        if not provided:
            record_device_sig_failure("store_no_sig")  # slice 28
            return None
        if not await store.verify(stripped, provided):
            record_device_sig_failure("store_verify_failed")  # slice 28
            return None
        return stripped
    # 폴백: 공유 HMAC secret(slice 21) 또는 검증 생략(slice 20)
    secret = settings.coach_device_hmac_secret.get_secret_value()
    if not secret:
        return stripped
    provided = request.headers.get("x-device-sig", "").strip()
    if not provided:
        record_device_sig_failure("shared_no_sig")  # slice 28
        return None
    expected = _expected_device_signature(secret, stripped)
    if not hmac.compare_digest(provided.lower(), expected):
        record_device_sig_failure("shared_invalid_sig")  # slice 28
        return None
    return stripped


async def _enforce_triple(
    user_id: uuid.UUID,
    ip: str | None,
    device_id: str | None,
    *,
    category: RateCategory,
    user_limit: int,
    ip_limit: int,
    device_limit: int,
    response: Response,
) -> None:
    """*3차원* 원자 한도 검사 — user + IP + device. 활성 차원만 검사·전부 통과 시 200.

    `hit_many` 호출로 race window 0 + 한쪽 거부 시 다른 차원 counter 낭비 0. 헤더는 세 쌍
    `X-RateLimit-User-*`/`-Ip-*`/`-Device-*` + rollup(가장 엄격한 쪽) 동봉.
    """
    subjects: list[Subject] = []
    if user_limit > 0:
        subjects.append(Subject(kind="user", id=str(user_id), limit=user_limit))
    if ip is not None and ip_limit > 0:
        subjects.append(Subject(kind="ip", id=ip, limit=ip_limit))
    if device_id is not None and device_limit > 0:
        subjects.append(Subject(kind="device", id=device_id, limit=device_limit))
    if not subjects:
        return
    results = await _BACKEND.hit_many(subjects, category=category, now=time.monotonic())
    # kind → (limit, result) 매핑 — 헤더 조립 입력
    pairs: dict[SubjectKind, tuple[int, RateLimitResult]] = {}
    for s in subjects:
        pairs[s.kind] = (s.limit, results[s.kind])
    # 모든 차원의 pair-headers 동봉(슬라이스 19 패턴 확장)
    pair_headers: dict[str, str] = {}
    if "user" in pairs:
        pair_headers.update(_pair_headers("User", *pairs["user"]))
    if "ip" in pairs:
        pair_headers.update(_pair_headers("Ip", *pairs["ip"]))
    if "device" in pairs:
        pair_headers.update(_pair_headers("Device", *pairs["device"]))
    # 어느 차원이 통과/거부 → 첫 차원 결과는 모두 동일 atomic
    first_result = next(iter(results.values()))
    if not first_result.allowed:
        # blocker = remaining=0인 쪽(다중 도달 시 user > ip > device 우선 — 더 강한 보호선)
        candidates: tuple[SubjectKind, ...] = ("user", "ip", "device")
        # 정상 거부 경로엔 적어도 한 차원이 remaining=0이라 break — fallback(next(iter))은
        # 방어선(예: 동시 prune·rounding 등의 edge case). 우선순위: user > ip > device.
        blocker_kind: SubjectKind = next(iter(pairs))
        for kind in candidates:  # pragma: no branch — break 또는 정상 종료 둘 다 의도된 경로
            if kind in pairs and pairs[kind][1].remaining == 0:
                blocker_kind = kind
                break
        blocker = pairs[blocker_kind]
        rollup = _rate_headers(*blocker)
        raise CodedHTTPException(
            "WM-RATE-001",
            detail="요청이 너무 많습니다(분당 한도 초과). 잠시 후 다시 시도하세요.",
            headers={
                "Retry-After": str(blocker[1].reset_seconds or 60),
                **rollup,
                **pair_headers,
            },
        )
    # 200: rollup(전체 차원 중 가장 엄격한 쪽) + 세 쌍 동봉
    tight_pair = min(pairs.values(), key=lambda p: p[1].remaining)
    for key, value in _rate_headers(*tight_pair).items():
        response.headers[key] = value
    for key, value in pair_headers.items():
        response.headers[key] = value


async def rate_limit_triple_read(
    user: ConsentedUser,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """*3차원 읽기* 한도(user+IP+device) — 인증 GET 엔드포인트의 강화 방어."""
    await _enforce_triple(
        user.user_id,
        _client_ip(request, settings=settings),
        await _client_device_id(request, settings),
        category="read",
        user_limit=settings.coach_rate_limit_read_per_minute,
        ip_limit=settings.coach_rate_limit_ip_read_per_minute,
        device_limit=settings.coach_rate_limit_device_read_per_minute,
        response=response,
    )


async def rate_limit_triple_write(
    user: ConsentedUser,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """*3차원 쓰기* 한도(user+IP+device) — 인증 POST 엔드포인트의 강화 방어."""
    await _enforce_triple(
        user.user_id,
        _client_ip(request, settings=settings),
        await _client_device_id(request, settings),
        category="write",
        user_limit=settings.coach_rate_limit_write_per_minute,
        ip_limit=settings.coach_rate_limit_ip_write_per_minute,
        device_limit=settings.coach_rate_limit_device_write_per_minute,
        response=response,
    )


RateLimitedTripleRead = Depends(rate_limit_triple_read)
"""인증 GET용 *3차원*(user+IP+device) 의존성 — `dependencies=[RateLimitedTripleRead]`."""

RateLimitedTripleWrite = Depends(rate_limit_triple_write)
"""인증 POST용 *3차원*(user+IP+device) 의존성 — `dependencies=[RateLimitedTripleWrite]`."""


# ──────────────────────────────────────────────────────────────────────────
# 슬라이스 25 — 디바이스 등록 전용 rate limit (`/v1/devices/register`)
#
# 등록 폭주 방어 — sock-puppet 디바이스 양산·DB 자격증명 행 폭증 차단. *낮은 한도*
# (user 5/min·IP 10/min)로 정상 사용자엔 무영향(첫 실행 1회·기기 변경)·자동화에만 발화.
# device 차원은 *N/A*(등록 *전*이라 device_id가 아직 없음) — user+IP 2차원만 적용.
# 별 category(`device_register`)로 coach write와 키 공간 분리 — 상호 영향 0.
# ──────────────────────────────────────────────────────────────────────────


async def rate_limit_device_register(
    user: ConsentedUser,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """디바이스 등록(`/v1/devices/register`) 전용 — user+IP 2차원·낮은 한도."""
    await _enforce_triple(
        user.user_id,
        _client_ip(request, settings=settings),
        None,  # device_id N/A — 등록 전엔 device가 없음(device 차원 자동 비활성)
        category="device_register",
        user_limit=settings.device_register_rate_limit_per_minute,
        ip_limit=settings.device_register_rate_limit_ip_per_minute,
        device_limit=0,
        response=response,
    )


RateLimitedDeviceRegister = Depends(rate_limit_device_register)
"""디바이스 등록 전용(slice 25) — `dependencies=[RateLimitedDeviceRegister]`."""


async def rate_limit_visualization(
    user: ConsentedUser,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> None:
    """시각화 생성(LLM·비용) 전용 — 3차원·coach write와 버킷 분리(slice 97)."""
    await _enforce_triple(
        user.user_id,
        _client_ip(request, settings=settings),
        await _client_device_id(request, settings),
        category="visualization",
        user_limit=settings.visualization_rate_limit_per_minute,
        ip_limit=settings.visualization_rate_limit_ip_per_minute,
        device_limit=settings.visualization_rate_limit_device_per_minute,
        response=response,
    )


RateLimitedVisualization = Depends(rate_limit_visualization)
"""시각화 LLM 엔드포인트 전용(slice 97) — `dependencies=[RateLimitedVisualization]`."""


# ──────────────────────────────────────────────────────────────────────────
# 슬라이스 17 — 사용자 + IP 동시 적용(방어 심층)
# 인증된 엔드포인트에 둘 다 부착해 ① 단일 사용자 학대 ② 공유 NAT의 단일 IP 학대 모두 차단.
# 429는 *먼저 실패*한 쪽 헤더로(사용자 우선). 200 헤더는 *더 엄격한* 쪽 노출(클라이언트가
# 가장 가까운 한도를 인식).
# ──────────────────────────────────────────────────────────────────────────


# 슬라이스 17-19의 `_tightest_headers`(2-pair)은 슬라이스 20의 3차원 일반화 인라인
# `min(pairs.values(), key=remaining)`로 흡수. clean cut(CLAUDE.md "범위 밖 기능 금지").


# 슬라이스 17-19의 Defense(user+IP 2차원) deps·`_enforce_defense`·`_tightest_headers`는
# 슬라이스 20의 Triple(user+IP+device 3차원) deps 도입으로 *모두 대체*됨(clean cut).
# 호출자 0 — 죽은 코드 제거(CLAUDE.md "범위 밖 기능 금지"). user+IP만 원하면 Triple에서
# `device_limit=0`으로 동등 동작. hit_both Protocol 메서드는 유지(슬라이스 18 API).
