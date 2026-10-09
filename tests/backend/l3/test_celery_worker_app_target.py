"""QUALITY 워커 기동 대상(`-A`)이 실제 celery의 해석을 통과하는가 (OPS-27 — 동적 검증).

`docker-compose.prod.yml`의 `quality-worker`는 `celery -A <대상> worker -c 1`로 뜬다. 정적 배선
(서비스 실재·AST 형식)은 `tests/infra/test_quality_worker_compose.py`가 항상 도는 `infra-contracts`
잡에서 지킨다. 그러나 그 잡에는 celery가 없어 "이 `-A` 값을 **celery가 실제로** 어떻게 해석하는가"는
볼 수 없다. 이 파일이 그 몫이다 — celery CLI가 `-A`를 해석하는 함수(`find_app`)를 그대로 호출한다.

왜 필요한가: 이전 판의 문서·systemd 유닛은 팩토리 함수를 `-A`에 직접 지정하는 형식을 "정전 명령"
이라 적었으나, Celery 5.6 CLI는 그 값에서 인스턴스가 아닌 함수를 받아 `AttributeError: 'function'
object has no attribute 'user_options'`로 기동 즉시 죽는다(2026-10-08 실측). 소스를 읽는 것만으로는
드러나지 않고 CLI를 실제로 돌려야만 드러나는 결함이었다.

hermetic: 브로커에 연결하지 않는다(`find_app`과 `app.tasks` 조회만 한다 — 앱 생성은 지연 연결).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from celery import Celery
from celery.app.utils import find_app

from whymath_backend.l3.queue.celery_app import WORKER_CONCURRENCY
from whymath_backend.l3.queue.tasks import QUALITY_TASK_NAME

# tests/backend/l3/<이 파일> → parents[3] = 레포 루트
_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.prod.yml"


def _worker_command() -> list[str]:
    data: dict[str, Any] = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    command = data["services"]["quality-worker"]["command"]
    assert isinstance(command, list)
    return [str(part) for part in command]


def _flag_value(command: list[str], flag: str) -> str:
    assert flag in command, f"{flag}가 워커 명령에 없다: {command}"
    return command[command.index(flag) + 1]


def _resolved_app() -> Celery:
    app = find_app(_flag_value(_worker_command(), "-A"))
    assert isinstance(app, Celery), (
        f"`-A` 대상이 celery 인스턴스로 해석되지 않는다: {type(app).__name__} — "
        "celery CLI는 이 값에서 인스턴스를 기대한다(함수면 기동 즉시 AttributeError)"
    )
    return app


def test_compose_app_target_resolves_to_a_celery_instance() -> None:
    """compose의 `-A` 값을 celery가 해석하면 Celery 인스턴스다(팩토리 함수가 아니다)."""
    _resolved_app()


def test_resolved_app_has_the_quality_task_registered() -> None:
    """워커가 로드하는 그 앱에 QUALITY 태스크가 등록돼 있다.

    producer(`CeleryJobQueue`)는 태스크 *이름*으로 send_task한다. 워커 앱에 그 이름이 없으면
    워커는 `Received unregistered task`로 메시지를 버린다 — 큐는 비는데 작업은 처리되지 않는다.

    주의: `@app.task`는 기본 `shared=True`라 어느 앱에 등록하든 이후 finalize되는 모든 앱에 보인다
    (2026-10-08 최소 예제로 확인). 그래서 이 검사가 보는 것은 "등록 호출이 *어딘가에* 있는가"이며,
    "어느 변수에 등록했는가"는 런타임 동작을 바꾸지 않는다.
    """
    assert QUALITY_TASK_NAME in _resolved_app().tasks


def test_resolved_app_concurrency_matches_the_start_flag() -> None:
    """앱 설정(`worker_concurrency`)·코드 상수·compose의 `-c`가 모두 같은 1이다(이중 방어)."""
    app = _resolved_app()
    assert int(_flag_value(_worker_command(), "-c")) == WORKER_CONCURRENCY == 1
    assert app.conf.worker_concurrency == WORKER_CONCURRENCY
