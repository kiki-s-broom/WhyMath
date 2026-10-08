"""Celery 앱 구성 — QUALITY(27b) 비동기 큐의 기반 (M1.2-live S4).

QUALITY(qwen3.5:27b)는 *동기 호출이 금지*된다(p50≈14초, GPU 100% 단일 점유 →
병렬 미작동, 03a §D.3·§A.1). 따라서 QUALITY로 라우팅된 요청은 이 Celery 앱의
작업 큐로 들어가 백그라운드 워커가 처리하고, 호출자는 job_id로 결과를 폴링한다.

설계 정본: `docs/architecture/03a_l3_router_design.md` §D.3(QUALITY 비동기 큐 경로)·
§A.1(27b 병렬 미작동). broker·result-backend는 Redis(config의 effective_celery_*)
이며, S2 RedisCache와 같은 Redis 인스턴스를 기본 재사용한다(단일 Redis로 캐시+큐).

지연 import 패턴 (providers/ollama.py·cache/redis_cache.py·trace/langfuse_sink.py의
`_build_default_client` 미러링): `celery` 라이브러리가 없거나 broker가 죽어 있는
환경(CI 단위테스트)에서도 모듈 import가 깨지지 않도록 Celery 앱은 *호출 시점에만*
생성한다. 앱 객체 생성 자체는 broker에 연결하지 않는다(첫 디스패치 때 연결).

────────────────────────────────────────────────────────────────────────────
워커 동시성 = 1 (GPU 단일 점유, 03a §D.3) — 절대 1을 넘기지 말 것
────────────────────────────────────────────────────────────────────────────
QUALITY(27b)는 GPU를 100% 단일 점유하므로 동시성을 올려도 throughput 이득이 없고
p50만 폭발한다(03a §A.1 c=4에서 ~0% 증가, §D.3). 동시성 1은 두 곳에서 강제한다:
  1. *앱 설정* `worker_concurrency=1` — 워커가 별도 `-c` 없이 떠도 1로 동작.
  2. *워커 기동 명령*에서 명시 — 운영은 아래 명령으로 워커를 띄운다(중복 안전장치):

        celery -A whymath_backend.l3.queue.tasks:quality_celery_app worker -c 1

     (또는 `--concurrency=1`). `-c 1`을 빼면 Celery 기본값(CPU 코어 수)이 되어
     GPU를 여러 워커가 다투게 되므로 *반드시* 1로 띄운다(앱 설정과 중복이지만,
     운영 실수 방지를 위한 이중 방어). solo 풀(`--pool=solo`)도 동시성 1과 동치다.

────────────────────────────────────────────────────────────────────────────
`-A`에는 이 모듈의 팩토리(`build_celery_app`)가 아니라 *모듈 수준 인스턴스*를 준다
────────────────────────────────────────────────────────────────────────────
`celery` CLI는 `-A` 값을 Celery **인스턴스**로 기대한다. 이 모듈의 팩토리 함수를 `-A`에 직접
지정하면 CLI가 함수를 받아 `AttributeError: 'function' object has no attribute
'user_options'`로 워커가 기동 즉시 죽는다(Celery 5.6.3 실측, 2026-10-08 OPS-27). 이전 판의
docstring·systemd 유닛이 그 형식을 "정전 명령"이라 적었으나 실제로는 동작하지 않았다.
QUALITY 태스크가 등록된 인스턴스는 `l3/queue/tasks.py`의 `quality_celery_app`이며(import 시
`build_celery_app()` + `register_quality_task`), 컨테이너 배포는 `docker-compose.prod.yml`의
`quality-worker` 서비스가 위 명령으로 띄운다. 형식 회귀는
`tests/infra/test_quality_worker_compose.py`(정적)·`tests/backend/l3/test_celery_worker_app_target.py`
(실제 celery 해석)가 막는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from whymath_backend.config import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover — 타입 체크 전용(런타임 import 회피)
    from celery import Celery

# Celery 앱 이름 — Langfuse 이벤트 이름·태스크 네임스페이스 접두사로도 쓰인다.
CELERY_APP_NAME = "whymath_l3_quality"

# 워커 동시성 — GPU 단일 점유(03a §D.3). 절대 1을 넘기지 말 것(모듈 docstring 참조).
WORKER_CONCURRENCY = 1


def build_celery_app(settings: Settings | None = None) -> Celery:
    """Celery 앱을 생성한다 (지연 import — providers/ollama.py 패턴 미러링).

    `celery` 라이브러리가 없는 환경에서도 이 모듈 import가 깨지지 않도록 *호출 시점에만*
    `celery`를 import한다. 앱 *생성*은 broker에 연결하지 않으므로(첫 디스패치 때 연결)
    라이브 Redis 없이도 안전하다.

    설정 (03a §D.3·§A.1):
      - broker·result-backend = Redis(effective_celery_*; 기본 redis_url 재사용).
      - 직렬화 = JSON 전용(task/result/accept) — payload는 RoutingDecision.model_dump()
        등 JSON-safe dict만 오가므로 pickle을 *쓰지 않는다*(보안·이식성).
      - worker_concurrency = 1(GPU 단일 점유). 워커 기동 명령에서도 `-c 1`로 중복 강제.
      - result_extended = True — 결과 메타(상태 등) 보존으로 폴링 응답을 풍부하게.

    Args:
        settings: 주입 설정(테스트). None이면 캐시된 전역 Settings.

    Returns:
        구성된 Celery 앱.
    """
    resolved = settings if settings is not None else get_settings()
    try:
        from celery import Celery
    except ImportError as exc:  # pragma: no cover — 환경 의존(라이브러리 미설치)
        raise RuntimeError(
            "celery가 설치되지 않았습니다. `pip install celery` 후 다시 시도하세요."
        ) from exc

    app = Celery(
        CELERY_APP_NAME,
        broker=resolved.effective_celery_broker_url,
        backend=resolved.effective_celery_result_backend,
        # 태스크 모듈을 명시 포함 — autodiscover 없이 결정적으로 등록(워커·테스트 일관).
        include=["whymath_backend.l3.queue.tasks"],
    )
    app.conf.update(
        # 직렬화: JSON 전용. payload는 JSON-safe dict만(RoutingDecision.model_dump()).
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # 워커 동시성 1 — GPU 단일 점유(03a §D.3). 기동 명령 `-c 1`과 이중 방어.
        worker_concurrency=WORKER_CONCURRENCY,
        # 한 번에 1개만 prefetch — 동시성 1과 정합(긴 27b 작업을 쌓아두지 않음).
        worker_prefetch_multiplier=1,
        # 결과 메타 확장 — 폴링 응답에 상태/이름 등을 보존.
        result_extended=True,
        # UTC 고정(타임존 모호성 제거) — 운영 일관성.
        enable_utc=True,
        timezone="UTC",
    )
    # cast 사유: celery는 py.typed를 제공하지 않아(ignore_missing_imports=true) Celery가
    # mypy에 Any로 보인다. 반환 타입을 명시 Celery로 좁힌다 — ollama/redis/langfuse의
    # 좁은 시임 + cast 처리와 동일한 방침(타입 무시 X, 정밀도만 좁힘).
    return cast("Celery", app)
