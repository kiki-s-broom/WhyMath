"""Redis 응답 캐시 — interfaces.CacheBackend 구현 (M1.2-live S2).

라우터가 만든 캐시 키(03a §F.1, `cache_key_for` — `{cost_tier}:{local_family}:
{local_model}`이 포함된 불투명 키)로 응답을 Redis에 저장·조회한다. *키 의미는
라우터가 책임지고*, 이 백엔드는 키-값 + TTL 저장이라는 *영속 계층*만 담당한다
(L5 다중 저장소 운영 책임 — Redis는 세션·핫 데이터 캐시).

설계 정본: `docs/architecture/03a_l3_router_design.md` §F.1(캐시 키 의미). 테스트
주입·지연 import 패턴은 providers/ollama.py(`_OllamaClient` 시임 + `_build_default_client`)
를 미러링한다. S1이 세운 패턴을 그대로 따른다.

경계 메모 (CLAUDE.md): 캐시에 저장되는 텍스트는 *검증 전 원시 모델 출력*이다 —
캐시 적중으로 반환된 값도 03 환각 방어 파이프라인 통과 전에는 학생 직접 노출 금지.
캐시 키는 학생 ID를 포함하지 않으므로(03a §F.1) 캐시 자체에 PII는 들어가지 않는다.

장애 강등 (OPS-05 — 왜 이 백엔드가 예외를 삼키는가)
--------------------------------------------------
캐시는 *성능 보완재*지 정답의 원천이 아니다. 그래서 `/health/ready`는 Redis를
`required=false`로 두고 미도달을 "강등"으로 본다. 그런데 OPS-04 조사에서 그 *정책*과
실제 *동작*이 어긋나 있었다: get/set이 예외를 그대로 올려 보내 Redis 다운 시
`l3/pipeline.generate`의 `cache.get`이 터지고 **학생 대면 생성 경로가 5xx**로 죽었다
(`docs/standards/incident_response_slo.md` 함정 ④). 이 모듈은 그 간극을 닫는다 —
네트워크 실패의 *발원지*에서 한 번에 막아, 소비처(파이프라인·L4 DSL 캐시·OCR 등)가
각자 try/except를 흩뿌리지 않게 한다.

강등 의미론은 CLAUDE.md 의사결정 우선순위(#1 학생 안전·웰빙 ≫ #6 비용·효율)의 직접
구현이다: **get 실패 → None(미스와 동일)** 이면 재생성되어 학생은 서비스를 받고, 대가는
LLM 재호출 비용뿐이다. **set 실패 → no-op(best-effort)** 이면 다음 요청이 재생성할 뿐이다.
둘 다 "비용을 더 쓰고 학생을 지킨다"는 교환이며, 그 반대(비용을 아끼려 학생 요청을
5xx로 죽임)는 우선순위 위반이다.

삼키되 침묵하지 않는다 (CLAUDE.md 침묵 실패 금지): 흡수 지점마다 **예외 타입명**을
warning 로그에 남기고(`type(exc).__name__` — 키·값·시크릿은 절대 로그하지 않는다.
캐시 키는 프롬프트 해시라 민감할 수 있다), 강등 횟수를 **인프로세스 카운터**로 센다
(`CacheDegradationCounter` — 외부 관측 인프라가 죽어도 판정치가 남는 이중 회계,
`ops/service_health.ServiceMetrics` 선례).

회로 차단 — 강등 중에는 Redis를 아예 부르지 않는다 (OPS-149)
------------------------------------------------------------
위의 강등은 *예외를 삼킬 뿐* Redis를 기다리는 비용은 그대로 낸다. OPS-146 실측: Redis가
없으면 캐시 연산 하나가 소켓 타임아웃(2.0초)까지 매달리고(연산당 중앙값 2,016ms), WH-1 한
턴이 캐시 연산을 15회 하므로 턴 소요의 94~95%가 캐시 대기였다(R2·R3). 캐시는 성능
보완재인데 죽은 캐시를 기다리는 비용이 캐시가 아끼는 비용보다 커진 것이다.

그래서 연속 N회(`cache_breaker_failure_threshold`, 기본 3) 실패하면 T초(`cache_breaker_
open_seconds`, 기본 30)간 get/set이 Redis를 부르지 않고 즉시 미스/no-op으로 강등한다.
T초가 지나면 첫 호출 1건만 시험(half-open)으로 Redis를 부르고 — 성공하면 닫고 실패하면 다시
T초 연다. 시험 중 도착한 다른 호출은 계속 우회한다(죽은 Redis에 대기가 쌓이지 않게).

- **건강한 Redis를 오탐 차단하지 않는다**: 연속 실패만 센다(성공 1건이 카운트를 0으로 되돌린다).
  R4 실측 정상 Redis는 연산 최대 94ms·강등 0회라 타임아웃과 20배 넘게 떨어져 있다.
- **취소에 안전하다**: WH-1은 15초 예산으로 턴을 취소하므로 시험 호출이 취소될 수 있다.
  취소된 시험이 슬롯을 반납하지 않으면 우회가 영구히 닫히지 않는다 — 취소도 시험 실패로
  거두고, 반납이 누락돼도 `cache_breaker_open_seconds` 뒤에는 새 시험을 허용한다.
- **우회도 강등으로 센다**: 건너뛴 호출은 `degradation_count`에 포함된다. 측정 도구
  (`scripts/ops/wh1_primary_timeout_decompose.py`)가 그 증가분으로 "강등으로 끝난 연산"을
  판정하므로, 세지 않으면 우회 구간이 정상으로 분류돼 redis-down 조건 확인이 혼합으로 거부된다.
- **작동한 비율**: 정상 응답 200은 우회가 일했다는 증거가 아니다. 열린 횟수·건너뛴 호출 수·
  우회 비율을 `CacheDegradationSnapshot`에 싣고 `/health/ready`의 `cache_degradation`로 노출한다.
`cache_breaker_failure_threshold=0`이면 우회를 끈다(종전 동작 — 코드 되돌림 없는 철수 수단).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Protocol, cast, runtime_checkable

from whymath_backend.config import Settings, get_settings

logger = logging.getLogger(__name__)

# 강등 회계의 연산 어휘 — 로그·스냅샷·테스트가 공유하는 단일 상수.
CacheOperation = Literal["get", "set"]
_OP_GET: CacheOperation = "get"
_OP_SET: CacheOperation = "set"

# 회로 차단 기본값 — config.py `cache_breaker_*`의 기본값과 같다(근거는 거기 description).
_DEFAULT_BREAKER_FAILURE_THRESHOLD = 3
_DEFAULT_BREAKER_OPEN_SECONDS = 30.0


class _Admission(Enum):
    """캐시 연산 1건이 Redis를 부를 수 있는가의 판정 — `CacheDegradationCounter.admit`의 결과."""

    CALL = "call"  # 정상 호출(회로 닫힘 또는 우회 꺼짐)
    PROBE = "probe"  # 우회 시간이 지난 뒤의 시험 호출(half-open) — 이 한 건만 Redis를 부른다
    SKIP = "skip"  # 우회 — Redis를 부르지 않고 미스/no-op으로 강등한다


# 로그 스팸 방지: 연속 실패가 이어지는 동안 매 요청 warning을 찍으면 로그가 알림 가치를
# 잃는다(AlertLogNotifier의 '상태 전이 시에만' 원칙). 전이(첫 실패) + 이후 N번째마다만
# 남긴다 — N번째를 남기는 이유는 장애가 *지속 중*임을 로그만 보고도 알 수 있게 하기 위함.
_LOG_EVERY_N_FAILURES = 100


# ──────────────────────────────────────────────────────────────────────────
# Redis 클라이언트 추상화 (테스트 주입용) — ollama.py `_OllamaClient` 패턴 미러링.
# 실제 `redis.asyncio.Redis`와 동형이지만 테스트는 인메모리 가짜로 대체한다.
# 우리가 *실제로 쓰는* 메서드(get·set(ex=)·ping)만 좁게 선언한다.
# ──────────────────────────────────────────────────────────────────────────
@runtime_checkable
class _RedisClient(Protocol):
    """redis.asyncio.Redis의 최소 인터페이스 (구조적 타이핑).

    `redis.asyncio.Redis`의 부분집합. 반환 타입은 클라이언트의 `decode_responses`
    설정에 따라 bytes 또는 str일 수 있어 `Any`로 두고, 캐시 쪽에서 방어적으로
    정규화한다(get_default 클라이언트는 decode_responses=True로 str을 받지만,
    주입된 가짜·다른 설정이 bytes를 줄 수 있어 양쪽을 흡수한다).
    """

    async def get(self, name: str) -> Any:
        """키로 값 조회 (없으면 None)."""
        ...

    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> Any:
        """키-값 저장. `ex`는 만료 초(None이면 무기한). redis SET name value EX ex."""
        ...

    async def ping(self) -> Any:
        """연결 도달성 확인 (redis PING). 도달 시 True/PONG, 실패 시 예외."""
        ...


# ──────────────────────────────────────────────────────────────────────────
# 강등 회계 — 인프로세스 축(SaaS·외부 관측 인프라 독립).
#
# 동시성 메모: 스레드-안전 장치를 두지 않는다 — 카운터 갱신은 await 없는 순수 동기
# 구간이라 asyncio 단일 이벤트 루프에서 코루틴 인터리브로 쪼개지지 않는다(락 불요·명시적
# 결정, `ops/service_health` 동시성 메모와 동일 전제). 다중 *워커*(프로세스)는 워커별
# 독립 회계다.
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class CacheDegradationSnapshot:
    """캐시 강등 회계의 불변 스냅샷 — 노출·단정은 이 스냅샷 기준(읽는 중 변형 방지).

    `last_error_type`은 *가장 최근에 흡수한* 예외의 타입명이다(값·키는 담지 않는다).
    강등이 한 번도 없었으면 None — '오류 없음'이지 '오류를 모름'이 아니다(실패 시에만
    채워지는 필드라 None-vs-0 혼동이 없다).
    """

    get_failures: int
    set_failures: int
    consecutive_failures: int
    last_error_type: str | None
    # ── 회로 차단(OPS-149) "작동한 비율" — 뒤에 기본값으로 붙여 기존 4필드 생성자를 보존한다 ──
    successes: int = 0  # Redis가 실제로 응답한 연산 수(우회 비율의 분모 일부)
    breaker_opens: int = 0  # 회로가 닫힘→열림으로 넘어간 횟수(시험 실패 재개방은 세지 않는다)
    skipped_calls: int = 0  # 우회로 Redis를 부르지 않고 미스/no-op 처리한 연산 수
    breaker_open: bool = False  # 지금 회로가 열려 있는가(= 다음 연산이 우회될 수 있는가)

    @property
    def total_failures(self) -> int:
        """누적 강등 횟수(get+set) — Redis를 *실제로 불러서* 실패한 횟수. 우회는 포함하지 않는다."""
        return self.get_failures + self.set_failures

    @property
    def bypass_ratio(self) -> float | None:
        """우회가 일한 비율 = 건너뛴 연산 / 전체 연산(성공 + 실패 + 건너뜀).

        분모가 0이면 None이다 — '연산 0건 중 0건'이 아니라 *측정 대상이 없다*(None-vs-0).
        1.0에 가까우면 거의 모든 캐시 연산이 Redis 없이 처리됐다는 뜻이다.
        """
        total = self.successes + self.total_failures + self.skipped_calls
        return self.skipped_calls / total if total else None

    @property
    def degraded(self) -> bool:
        """지금 강등 중인가 = 마지막으로 *관측된* 캐시 연산이 실패였는가.

        트래픽이 없으면 마지막 관측 그대로 남는다(오래된 True는 '그 후 시도가 없었다'는
        뜻이지 '지금 확실히 죽었다'가 아니다). 실시간 도달성 판정은 `/health/ready`의
        Redis PING 딥체크가 따로 한다 — 이 플래그는 *실제 사용 경로*의 관측이다.
        """
        return self.consecutive_failures > 0


class CacheDegradationCounter:
    """강등 회계 + 로그 경로 — 실패를 세고, 상태 전이에서만 warning을 남긴다.

    로그 정책(테스트로 동결):
      - **첫 실패**(정상→강등 전이)는 반드시 warning — 예외 *타입명* 포함(침묵 실패 금지).
      - 연속 실패가 이어지면 `log_every_n_failures`번째마다만 warning(스팸 억제).
      - 성공이 다시 관측되면 info 1회(해소) 후 연속 카운터를 0으로 — 다음 장애는 다시
        첫 실패 warning을 낸다.
      - 로그에 **키·값·시크릿은 절대 싣지 않는다**(캐시 키 = 프롬프트 해시 → 민감 가능).

    회로 차단(OPS-149)도 이 객체가 *상태를 쥔다* — 테스트 격리(카운터를 새로 주입하면 회로도
    새로 시작)와 프로세스 합산(전역 카운터를 쓰는 인스턴스는 한 회로를 공유 — 죽은 Redis를
    인스턴스마다 3회씩 따로 두드리지 않는다)이 카운터 주입이라는 한 지점으로 묶이기 때문이다.
    시계는 주입 가능하다(`clock`, 기본 `time.monotonic`) — 시간 경과를 sleep 없이 검증한다.

    logger 주입은 테스트 격리용이다(`AlertLogNotifier` 선례).
    """

    def __init__(
        self,
        *,
        log_every_n_failures: int = _LOG_EVERY_N_FAILURES,
        target_logger: logging.Logger | None = None,
        breaker_failure_threshold: int = _DEFAULT_BREAKER_FAILURE_THRESHOLD,
        breaker_open_seconds: float = _DEFAULT_BREAKER_OPEN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._logger = target_logger if target_logger is not None else logger
        # 0·음수는 매 실패 로그(스팸)를 뜻하므로 최소 1로 클램프 — 설정 실수 방어.
        self._log_every_n = max(1, log_every_n_failures)
        self._get_failures = 0
        self._set_failures = 0
        self._consecutive_failures = 0
        self._last_error_type: str | None = None
        self._successes = 0
        # 회로 차단 상태. `_open_until is None`이면 닫힘, 아니면 그 시각(clock 기준)까지 열림 —
        # 시각이 지난 뒤에도 None이 되지 않고 열린 채 시험 호출을 기다린다(half-open).
        self._clock = clock
        self._breaker_threshold = breaker_failure_threshold
        self._breaker_open_seconds = breaker_open_seconds
        self._open_until: float | None = None
        self._probe_started_at: float | None = None  # 시험 호출이 나간 시각(None이면 시험 없음)
        self._breaker_opens = 0
        self._skipped_calls = 0

    # ── 회로 차단 ────────────────────────────────────────────────────────────
    def configure_breaker(self, *, failure_threshold: int, open_seconds: float) -> None:
        """설정값 반영 — RedisCache가 첫 사용 때 Settings 값으로 부른다(멱등·마지막 값 우선).

        전역 카운터는 import 시점에 만들어져 Settings를 모른다. 같은 프로세스의 모든 인스턴스는
        같은 Settings를 쓰므로 값이 같고, 달라도 마지막 값이 이긴다(테스트 격리는 카운터 주입).
        """
        self._breaker_threshold = failure_threshold
        self._breaker_open_seconds = open_seconds

    def admit(self) -> _Admission:
        """이 연산이 Redis를 불러도 되는가 — 우회면 건너뜀을 센다(작동한 비율의 분자).

        - 우회 꺼짐(threshold<=0) 또는 회로 닫힘 → CALL.
        - 열림 시간 안 → SKIP.
        - 열림 시간이 지남: 진행 중인 시험이 없으면 이 호출이 시험(PROBE), 있으면 SKIP.
          단 시험이 `breaker_open_seconds` 넘게 끝나지 않았으면 반납이 누락된 것으로 보고 새
          시험을 허용한다(영구 우회 방지 안전망 — 취소·예외 경로가 모두 반납하지만 방어선을 둔다).
        """
        if self._breaker_threshold <= 0 or self._open_until is None:
            return _Admission.CALL
        now = self._clock()
        if now < self._open_until:
            self._skipped_calls += 1
            return _Admission.SKIP
        if (
            self._probe_started_at is not None
            and now - self._probe_started_at < self._breaker_open_seconds
        ):
            self._skipped_calls += 1
            return _Admission.SKIP
        self._probe_started_at = now
        return _Admission.PROBE

    def abort_probe(self, admission: _Admission) -> None:
        """시험 호출이 *성공도 실패도 아닌 채* 끝났을 때(취소 등) 슬롯을 반납하고 재개방한다.

        취소는 Redis가 살아 있다는 증거가 아니므로 닫지 않는다. 시험이 아니면 아무것도 안 한다.
        """
        if admission is _Admission.PROBE:
            self._reopen("시험 호출이 취소됨")

    def _reopen(self, reason: str) -> None:
        """열림 시간을 지금부터 다시 시작하고 시험 슬롯을 비운다."""
        self._open_until = self._clock() + self._breaker_open_seconds
        self._probe_started_at = None
        self._logger.warning(
            "Redis 캐시 회로 차단 유지 — %s. %.1f초 뒤 다시 시험합니다.",
            reason,
            self._breaker_open_seconds,
        )

    def record_failure(
        self,
        operation: CacheOperation,
        exc: BaseException,
        *,
        admission: _Admission = _Admission.CALL,
    ) -> None:
        """강등 1건 기록 + 정책에 따라 warning 로그(예외 타입명 포함) + 회로 개폐 판정."""
        error_type = type(exc).__name__
        if operation == _OP_GET:
            self._get_failures += 1
        else:
            self._set_failures += 1
        self._consecutive_failures += 1
        self._last_error_type = error_type
        if self._consecutive_failures == 1 or self._consecutive_failures % self._log_every_n == 0:
            self._logger.warning(
                "Redis 캐시 강등 — operation=%s 예외 타입: %s (연속 %d회·누적 %d회). "
                "요청은 캐시 미스로 계속 처리됩니다(학생 노출 없음).",
                operation,
                error_type,
                self._consecutive_failures,
                self._get_failures + self._set_failures,
            )
        if self._breaker_threshold <= 0:
            return
        if admission is _Admission.PROBE:
            # 시험 실패 — 아직 죽어 있다. 열림 횟수는 올리지 않는다(같은 사건의 연장).
            self._reopen(f"시험 호출 실패(예외 타입: {error_type})")
        elif self._open_until is None and self._consecutive_failures >= self._breaker_threshold:
            # 닫힘→열림 전이. 이미 열린 뒤에 도착한 앞선 호출의 실패는 여기로 오지 않는다.
            self._open_until = self._clock() + self._breaker_open_seconds
            self._breaker_opens += 1
            self._logger.warning(
                "Redis 캐시 회로 차단 열림 — 연속 실패 %d회(마지막 예외 타입: %s). "
                "%.1f초간 Redis를 부르지 않고 캐시 없이 처리합니다(학생 노출 없음).",
                self._consecutive_failures,
                error_type,
                self._breaker_open_seconds,
            )

    def record_success(self, *, admission: _Admission = _Admission.CALL) -> None:
        """정상 캐시 연산 1건 관측 — 강등 중이었다면 해소를 info로 남기고 연속을 0으로.

        회로는 *시험 호출의 성공*으로만 닫는다. 열리기 전에 나간 호출이 뒤늦게 성공해도 그것은
        '지금 Redis가 산다'는 증거가 아니므로 닫지 않는다(연속 실패 카운트만 0으로 돌아간다).
        """
        self._successes += 1
        if self._consecutive_failures:
            self._logger.info(
                "Redis 캐시 강등 해소 — 직전 연속 실패 %d회(마지막 예외 타입: %s)",
                self._consecutive_failures,
                self._last_error_type,
            )
            self._consecutive_failures = 0
        if admission is _Admission.PROBE:
            self._open_until = None
            self._probe_started_at = None
            self._logger.info("Redis 캐시 회로 차단 닫힘 — 시험 호출이 성공했습니다.")

    def snapshot(self) -> CacheDegradationSnapshot:
        """현재 회계의 불변 스냅샷."""
        return CacheDegradationSnapshot(
            get_failures=self._get_failures,
            set_failures=self._set_failures,
            consecutive_failures=self._consecutive_failures,
            last_error_type=self._last_error_type,
            successes=self._successes,
            breaker_opens=self._breaker_opens,
            skipped_calls=self._skipped_calls,
            breaker_open=self._open_until is not None,
        )

    def reset(self) -> None:
        """회계 초기화 — 테스트 격리용(프로덕션 경로는 호출하지 않는다). 회로도 닫는다."""
        self._get_failures = 0
        self._set_failures = 0
        self._consecutive_failures = 0
        self._last_error_type = None
        self._successes = 0
        self._open_until = None
        self._probe_started_at = None
        self._breaker_opens = 0
        self._skipped_calls = 0


# 프로세스 전역 회계 — RedisCache 인스턴스가 여럿(app.state 기본 캐시·사전적재 CLI 등)이어도
# "이 프로세스가 캐시 없이 버틴 횟수"는 하나로 합산돼야 운영 판정이 된다. 인스턴스별 격리가
# 필요한 테스트는 `RedisCache(degradation=CacheDegradationCounter())`로 새 카운터를 주입한다.
_PROCESS_DEGRADATION = CacheDegradationCounter()


def cache_degradation_snapshot() -> CacheDegradationSnapshot:
    """프로세스 전역 캐시 강등 회계 스냅샷 — 운영 노출·진단의 읽기 표면.

    `/health/ready` body의 `cache_degradation` 섹션이 이 접근자를 읽는다(OPS-149 — 회로 차단의
    '작동한 비율'을 정상 200 뒤에 숨기지 않기 위한 배선). 관측 SaaS 없이도 읽을 수 있다.
    프로세스별 카운터다 — 서버 워커가 여럿이면 응답한 워커 1개의 값이고 재시작하면 0부터다.
    """
    return _PROCESS_DEGRADATION.snapshot()


def reset_cache_degradation() -> None:
    """프로세스 전역 회계 초기화 — 테스트 격리용."""
    _PROCESS_DEGRADATION.reset()


def _decode(value: Any) -> str | None:
    """Redis get 응답을 str | None으로 방어적 정규화.

    클라이언트가 `decode_responses=True`면 str, 아니면 bytes를 돌려준다. 키 미스는
    None이다. bytes는 UTF-8로 디코드하고, 그 외 예기치 못한 타입은 None으로 본다
    (캐시는 우리가 set한 str만 들어 있어야 하므로, 비정상 값은 미스로 처리해 안전).
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8")
    return None


def _build_default_client(settings: Settings) -> _RedisClient:
    """기본 redis.asyncio 클라이언트 생성 (지연 import).

    `redis` 라이브러리/데몬이 없는 환경(CI 단위테스트)에서도 모듈 import가 깨지지
    않도록 *호출 시점에만* import한다 (ollama.py `_build_default_client` 패턴). 앱
    구성만으로는 라이브 Redis가 필요 없고, 첫 캐시 접근 때 비로소 연결을 만든다.

    `decode_responses=True`로 만들어 get이 str을 돌려주게 한다(디코딩 일관성 — 코드
    쪽 `_decode`는 주입 가짜가 bytes를 줄 경우의 방어선이다). URL은 설정에서 받으며
    인증이 필요하면 URL 자체에 환경변수로 주입한다(CLAUDE.md 보안 금기: 하드코딩 X).

    **소켓 타임아웃을 명시한다** (OPS-05): 무응답 Redis(패킷 블랙홀·방화벽 drop)는
    연결 거부(즉시 예외)보다 나쁘다 — 요청이 응답을 기다리며 매달리고, asyncio 워커가
    고갈되면 캐시 한 컴포넌트의 장애가 서비스 전체 마비로 번진다. 실측(설치본 redis-py
    8.0.1): `Redis.from_url(...)`에 타임아웃을 주지 않으면 connection_kwargs에 키 자체가
    들어가지 않고 Connection 기본값(5초)이 적용된다 — 즉 **값이 라이브러리 버전 기본값에
    종속**된다(pin `redis>=5.1.0`은 상한이 없어 버전에 따라 달라질 수 있다). 명시
    지정으로 버전 비의존이 되고, 값도 학생 요청 예산에 맞게(기본 2.0초) 좁힌다.
    타임아웃은 예외로 드러나 `RedisCache.get/set`이 캐시 미스로 강등한다 — 즉 이 설정의
    효과는 '요청 실패'가 아니라 '캐시 없이 계속 진행'이다.
    """
    try:
        from redis.asyncio import Redis
    except ImportError as exc:  # pragma: no cover — 환경 의존(라이브러리 미설치)
        raise RuntimeError(
            "redis Python 클라이언트가 설치되지 않았습니다. "
            "`pip install redis[hiredis]` 후 다시 시도하세요."
        ) from exc
    # cast 사유: redis-py의 from_url은 동기/비동기 공용 시그니처라 정밀 스텁이 우리의
    # 좁은 구조적 시임 `_RedisClient`와 형태가 어긋난다. 우리가 실제로 쓰는 호출 규약
    # (get·set(ex=)·ping)은 Redis가 런타임에 충족하므로 스텁 정밀도 차이만 cast로
    # 좁힌다(타입 무시 X — ollama.py가 AsyncClient를 다룬 방식과 동일).
    timeout_s = settings.redis_socket_timeout_s
    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        # 응답 대기(socket_timeout)·연결 수립(socket_connect_timeout) 둘 다 건다 — 하나만
        # 걸면 나머지 축에서 무한 대기가 그대로 남는다(연결은 되는데 응답이 없는 블랙홀,
        # 반대로 SYN이 drop되는 방화벽 — 두 실패 양상이 서로 다른 인자에 걸린다).
        socket_timeout=timeout_s,
        socket_connect_timeout=timeout_s,
    )
    return cast(_RedisClient, client)


class RedisCache:
    """Redis 기반 응답 캐시 — interfaces.CacheBackend 충족.

    파이프라인은 라우터가 만든 키로 get/set만 호출하고(03a §F.1), 이 백엔드는 그 키를
    *불투명하게* Redis에 저장·조회한다. TTL은 redis 네이티브 만료(SET ... EX)로
    실제 적용된다(InMemoryCache는 기록만 했던 것과 대비 — S2의 핵심 차이).

    클라이언트는 지연 생성(lazy)·주입 가능(injectable)하다 — 테스트는 인메모리 가짜
    클라이언트를 `client=`로 넣고, 프로덕션은 기본 redis.asyncio 클라이언트를 첫
    사용 시 생성한다(라이브 Redis 없이도 앱 구성·단위테스트가 가능하도록).

    **장애 강등(OPS-05)**: get/set은 어떤 예외도 호출자에게 전파하지 않는다 — get 실패는
    미스(None), set 실패는 no-op으로 강등하고 예외 타입명을 로그·카운터에 남긴다. 근거와
    우선순위 해석은 모듈 docstring '장애 강등' 절 참조.
    """

    def __init__(
        self,
        *,
        client: _RedisClient | None = None,
        settings: Settings | None = None,
        degradation: CacheDegradationCounter | None = None,
    ) -> None:
        # 주입된 클라이언트가 있으면 그것을 쓰고, 없으면 첫 사용 시 기본 생성(지연).
        self._client = client
        self._settings = settings
        # 기본은 프로세스 전역 회계(인스턴스가 여럿이어도 합산) — 테스트는 새 카운터 주입.
        self._degradation = degradation if degradation is not None else _PROCESS_DEGRADATION
        # 회로 차단 설정(Settings → 카운터) 반영 여부 — 첫 연산 때 한 번만(OPS-149).
        self._breaker_configured = False

    def _admit(self) -> _Admission:
        """연산 1건의 Redis 호출 허가 판정 — 첫 호출 때 회로 차단 설정을 카운터에 반영한다."""
        if not self._breaker_configured:
            settings = self._resolved_settings
            self._degradation.configure_breaker(
                failure_threshold=settings.cache_breaker_failure_threshold,
                open_seconds=settings.cache_breaker_open_seconds,
            )
            self._breaker_configured = True
        return self._degradation.admit()

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_client(self) -> _RedisClient:
        """클라이언트 지연 해석 — 주입 우선, 없으면 기본 클라이언트 생성."""
        if self._client is None:
            self._client = _build_default_client(self._resolved_settings)
        return self._client

    @property
    def degradation_count(self) -> int:
        """이 캐시가 쓰는 회계의 누적 강등 횟수(get+set) — 인프로세스 판정치.

        실패한 Redis 호출 **+ 회로 차단으로 건너뛴 연산**의 합이다(OPS-149). 둘 다 "캐시 없이
        버틴" 연산이고, 측정 도구가 이 값의 증가로 연산 1건의 강등 여부를 판정하기 때문이다.
        Redis를 실제로 불러 실패한 횟수만 필요하면 스냅샷의 `total_failures`를 쓴다.
        """
        snapshot = self._degradation.snapshot()
        return snapshot.total_failures + snapshot.skipped_calls

    def degradation_snapshot(self) -> CacheDegradationSnapshot:
        """이 캐시가 쓰는 회계의 불변 스냅샷(연산별 실패·연속 실패·마지막 예외 타입)."""
        return self._degradation.snapshot()

    async def get(self, key: str) -> str | None:
        """키로 캐시 조회. 미스면 None (CacheBackend 구현).

        반환값은 디코드된 str이다. redis가 bytes를 줄 수 있어 `_decode`로 방어적
        정규화한다(기본 클라이언트는 decode_responses=True라 보통 str). 반환 텍스트는
        *검증 전 원시 출력*이다(모듈 docstring 경계 메모 참조).

        **장애 강등(OPS-05)**: 연결 실패·타임아웃·프로토콜 오류 등 *어떤* 예외도 전파하지
        않고 **None(=캐시 미스)** 으로 강등한다. 미스는 파이프라인이 이미 아는 정상 상태라
        (재생성) 학생은 그대로 서비스받고, 비용만 더 든다 — CLAUDE.md 우선순위 #1(학생
        안전·웰빙) ≫ #6(비용·효율)의 직접 구현이다. 흡수해도 침묵하지 않는다: 예외
        타입명이 warning 로그와 강등 카운터에 남는다(키·값은 로그하지 않는다).

        try 범위에 클라이언트 지연 생성과 `_decode`까지 넣는 이유: 잘못된 redis_url·
        라이브러리 미설치(생성 단계 RuntimeError)·손상된 값(UnicodeDecodeError)도 결국
        "캐시를 못 쓰는 상태"라 같은 강등으로 다뤄야 학생 경로가 안 깨진다.
        """
        admission = self._admit()
        if admission is _Admission.SKIP:
            # 회로 차단 우회(OPS-149) — Redis를 부르지 않고 미스로 강등(건너뜀은 admit()이 셌다).
            return None
        try:
            raw = await self._get_client().get(key)
            decoded = _decode(raw)
        except Exception as exc:  # noqa: BLE001 — 캐시 장애를 학생 대면 실패로 전파 금지
            self._degradation.record_failure(_OP_GET, exc, admission=admission)
            return None
        except BaseException:
            # 취소(asyncio.CancelledError — WH-1 턴 예산 초과 등)는 성공도 실패도 아니다. 시험
            # 호출이었다면 슬롯을 반납하지 않는 한 우회가 영구히 닫히지 않으므로 거두고 전파한다.
            self._degradation.abort_probe(admission)
            raise
        self._degradation.record_success(admission=admission)
        return decoded

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """키-값 저장 + TTL 만료 (CacheBackend 구현).

        TTL 처리(엣지 케이스): redis는 `EX 0`(또는 음수)를 거부한다(ERR invalid
        expire time). 따라서 `ttl_seconds <= 0`이면 만료 인자 없이 저장한다 — 즉
        *무기한 보관*으로 폴백한다. 호출자가 양수 TTL을 주면 redis 네이티브 만료를
        그대로 사용한다(InMemoryCache의 '기록만'과 달리 실제로 만료됨).

        무기한 폴백을 택한 이유: 캐시 set은 best-effort 부수효과이므로(미스 시 재생성
        가능) 비정상 TTL 때문에 호출을 실패시키기보다, 값은 저장하되 만료만 생략하는
        쪽이 파이프라인 가용성에 안전하다. 정상 운영에서 `cache_ttl_s`는 양수다
        (config 기본 3600, ge=0). ttl=0은 '캐시 비활성'이 아니라 '만료 없음'으로
        해석됨에 유의(캐시 비활성화는 상위에서 결정).

        **장애 강등(OPS-05)**: 저장 실패는 예외를 전파하지 않고 **no-op**으로 강등한다
        (best-effort). 적재 실패의 유일한 대가는 다음 동일 요청의 재생성 비용이며, 그것
        때문에 지금 응답을 이미 만들어 낸 학생 요청을 5xx로 죽이는 것은 우선순위 위반이다
        (#1 학생 ≫ #6 비용). get과 마찬가지로 예외 타입명을 로그·카운터에 남긴다.
        """
        admission = self._admit()
        if admission is _Admission.SKIP:
            # 회로 차단 우회(OPS-149) — 적재를 건너뛴다(no-op). 다음 동일 요청이 재생성할 뿐이다.
            return
        try:
            client = self._get_client()
            if ttl_seconds <= 0:
                # EX 0/음수는 redis가 거부 → 만료 없이 저장(무기한 폴백).
                await client.set(key, value)
            else:
                await client.set(key, value, ex=ttl_seconds)
        except Exception as exc:  # noqa: BLE001 — 캐시 장애를 학생 대면 실패로 전파 금지
            self._degradation.record_failure(_OP_SET, exc, admission=admission)
            return
        except BaseException:
            # get과 같은 사유 — 취소된 시험 호출의 슬롯 반납(영구 우회 방지).
            self._degradation.abort_probe(admission)
            raise
        self._degradation.record_success(admission=admission)

    async def ping(self) -> bool:
        """Redis 도달성 확인 — 도달 True, 실패 False (예외 흡수).

        향후 레디니스(/status)용으로 제공한다. ollama의 check_status가 도달 불가를
        비크래시 상태로 흡수하듯, 연결 오류를 예외로 던지지 않고 False로 보고한다.

        반환 계약은 종전 그대로다(bool). OPS-05가 바꾼 것은 둘: ①이 호출도 기본
        클라이언트의 소켓 타임아웃 적용 대상이라 무응답 Redis에서 무한 대기하지 않는다
        ②흡수하되 예외 *타입명*을 debug 로그에 남긴다(침묵 실패 금지 — 값·키는 제외).
        warning이 아니라 debug인 이유: 레디니스 폴링 경로의 *정식* 보고 표면은
        `ops/service_health.check_redis`(타입명을 `/health/ready` body에 싣는다)이고,
        여기서 warning을 또 찍으면 같은 사건이 이중으로 시끄러워진다. 강등 카운터에도
        넣지 않는다 — 이 메서드는 *캐시 사용 경로*가 아니라 도달성 조회다(회계 오염 방지).
        """
        try:
            result = await self._get_client().ping()
        except Exception as exc:  # noqa: BLE001 — 도달 불가를 비크래시 False로 흡수
            logger.debug("Redis ping 실패 — 예외 타입: %s", type(exc).__name__)
            return False
        # redis ping은 보통 True(또는 b"PONG")를 돌려준다. 도달했으면 truthy.
        return bool(result)
