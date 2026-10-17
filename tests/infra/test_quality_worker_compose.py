"""QUALITY 비동기 워커 컨테이너 배선 동결 테스트 (hermetic — docker 데몬·celery 설치 불요).

OPS-27-quality-worker-container-deploy: `app`은 QUALITY(비동기 전용) 요청을 `CeleryJobQueue`로
상시 enqueue하는데(app.py 기본 큐 결선), prod compose에는 그 큐를 *소비하는* 프로세스가 없었다.
그래서 202로 접수된 작업이 영구 `pending`이었다(`GET /v1/jobs/{id}` 폴링은 있는데 작업을 끝낼
주체가 배포에 없음 — `docs/architecture/ai_integration_gap_review.md` D2). `quality-worker`
서비스가 그 소비자다. "서비스가 있다"와 "작업이 소비된다"는 다르므로(OPS-03/08/10/11 선례) 이 파일은
존재뿐 아니라 **실제로 동작하게 만드는 조건**을 동결한다:

  ① **서비스 실재 + 단일성** — `quality-worker`가 있고, celery 워커 서비스는 그것 하나뿐이다.
     워커가 둘이면 동시성이 2가 되어 GPU 단일 점유(03a §D.3)를 어긴다.
  ② **`-A` 대상은 모듈 수준 Celery 인스턴스** — 팩토리 함수(`build_celery_app`)를 가리키면 Celery
     5.6 CLI가 `AttributeError: 'function' object has no attribute 'user_options'`로 기동 즉시
     죽는다(2026-10-08 실측). 기존 systemd 유닛·docstring이 그 형식을 "정전 명령"이라 적었으나
     실제로는 동작하지 않았다. 대상이 함수로 돌아가는 회귀를 소스 AST로 막는다(이 잡에는 celery가
     없으므로 실제 해석과 태스크 등록 여부는 tests/backend가 맡는다 — 태스크는 기본 `shared=True`라
     어느 앱에 등록해도 모든 앱에 보이므로 "어느 변수에 등록했는가"는 AST로 판정할 수 없고 판정할
     필요도 없다. 2026-10-08 뮤테이션 C2에서 이 과잉 엄격 검사를 걷어냈다).
  ③ **동시성 1** — `-c 1`이며 `l3/queue/celery_app.py`의 `WORKER_CONCURRENCY`와 같다.
  ④ **이미지 재사용·재시작** — app과 동일 이미지(새 Dockerfile 0), `restart: unless-stopped`.
  ⑤ **같은 브로커·같은 Ollama** — app과 같은 Redis URL(비밀번호는 보간), 같은 Ollama 호스트와
     `host.docker.internal` 매핑. 다르면 enqueue한 곳과 소비하는 곳이 갈린다.
  ⑥ **최소 권한** — 워커는 DB·JWT·암호화 키·클라우드 키가 필요 없다(허용 목록 밖 env 금지).
  ⑦ **정상 종료 보장** — exec-form 명령(PID 1이 SIGTERM을 직접 받음) + `stop_grace_period`가
     진행 중인 QUALITY 생성을 끊지 않을 만큼 길다(끊기면 ack된 메시지가 재전달되지 않아 영구 pending).
  ⑧ **변별력 있는 헬스체크** — `celery inspect ping`을 **자기 노드(`-d celery@$$HOSTNAME`)**로
     한정한다. `-d`가 없으면 같은 브로커의 *다른* 워커가 응답해도 healthy가 되어, 이 컨테이너의 워커가
     죽어 있어도 정상으로 보이는 위장이 된다(2026-10-08 실측: 이웃 워커의 pong이 "워커 없음" 대조군을 오염).
  ⑨ **깨진 기동 명령 부재** — 팩토리 형식 `-A ...:build_celery_app`가 실행 가능한 문맥(compose·
     systemd·런북·운영 문서·소스 docstring)에 남아 있지 않다.

동적 검증(실제 celery로 `-A` 대상을 해석해 QUALITY 태스크 등록을 확인)은
`tests/backend/l3/test_celery_worker_app_target.py`가 맡는다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.prod.yml"
_BACKEND = _ROOT / "src" / "backend"
_CELERY_APP_PY = _BACKEND / "whymath_backend" / "l3" / "queue" / "celery_app.py"

# 워커 env 허용 목록 — 이 밖의 키가 필요해지면 *의식적으로* 이 목록과 근거를 함께 고친다.
_REQUIRED_ENV = {"WHYMATH_REDIS_URL", "WHYMATH_OLLAMA_HOST"}
_OPTIONAL_ENV = {
    "WHYMATH_LANGFUSE_PUBLIC_KEY",
    "WHYMATH_LANGFUSE_SECRET_KEY",
    "WHYMATH_LANGFUSE_HOST",
}

# 진행 중인 QUALITY 생성이 끊기지 않을 최소 유예(초). dense 27B p50≈14s를 넉넉히 넘기는 값.
_MIN_GRACE_SECONDS = 60


def _services() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    services: dict[str, Any] = data["services"]
    return services


def _worker() -> dict[str, Any]:
    services = _services()
    assert "quality-worker" in services, (
        "docker-compose.prod.yml에 quality-worker 서비스가 없다 — app은 QUALITY 요청을 상시 "
        "enqueue하므로 소비자가 없으면 202로 접수된 작업이 영구 pending이다(OPS-27 이전 상태)"
    )
    worker: dict[str, Any] = services["quality-worker"]
    return worker


def _command(service: dict[str, Any]) -> list[str]:
    command = service.get("command")
    assert isinstance(command, list), (
        f"command가 exec-form 리스트가 아니다: {command!r} — `sh -c` 래퍼는 SIGTERM을 전달하지 "
        "않아 워커가 warm shutdown 없이 SIGKILL로 끊긴다"
    )
    return [str(part) for part in command]


def _option_value(command: list[str], *flags: str) -> str | None:
    """`-A value`·`--app=value` 형태에서 값을 꺼낸다(없으면 None)."""
    for index, part in enumerate(command):
        if part in flags and index + 1 < len(command):
            return command[index + 1]
        for flag in flags:
            if flag.startswith("--") and part.startswith(flag + "="):
                return part.split("=", 1)[1]
    return None


def _app_target(command: list[str]) -> tuple[str, str]:
    target = _option_value(command, "-A", "--app")
    assert target and ":" in target, f"-A 대상이 `module:attr` 형식이 아니다: {target!r}"
    module, attr = target.split(":", 1)
    return module, attr


def _module_tree(module: str) -> ast.Module:
    path = _BACKEND.joinpath(*module.split(".")).with_suffix(".py")
    assert path.is_file(), f"-A 대상 모듈 파일이 없다: {path.relative_to(_ROOT)}"
    return ast.parse(path.read_text(encoding="utf-8"))


def _int_constant(path: Path, name: str) -> int:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, int)
            return value
    raise AssertionError(f"{path.relative_to(_ROOT)}에 상수 {name}이 없다")


def _grace_seconds(raw: object) -> int:
    match = re.fullmatch(r"(\d+)(s|m)", str(raw).strip())
    assert match, f"stop_grace_period를 해석할 수 없다: {raw!r}"
    return int(match.group(1)) * (60 if match.group(2) == "m" else 1)


# ──────────────────────────────────────────────────────────────────────
# ① 서비스 실재 + 단일성
# ──────────────────────────────────────────────────────────────────────
def test_quality_worker_service_exists() -> None:
    """① quality-worker가 compose에 있다 — 지우면 QUALITY 202 작업이 다시 영구 pending."""
    assert _worker()


def test_exactly_one_celery_worker_service() -> None:
    """① celery 워커 서비스는 하나뿐이다 — 둘이면 동시성 2로 GPU 단일 점유(03a §D.3)를 어긴다."""
    consumers = [
        name
        for name, svc in _services().items()
        if isinstance(svc.get("command"), list)
        and "celery" in [str(p) for p in svc["command"]]
        and "worker" in [str(p) for p in svc["command"]]
    ]
    assert consumers == ["quality-worker"], f"celery 워커 서비스가 하나가 아니다: {consumers}"


def test_container_name_pinned_so_scale_is_refused() -> None:
    """① container_name이 박혀 있다 — compose는 이런 서비스의 `--scale`을 거부해 워커 증식을 막는다."""
    name = str(_worker().get("container_name", ""))
    assert "${DEPLOY_ENV" in name and name.endswith("-quality-worker"), name


# ──────────────────────────────────────────────────────────────────────
# ② -A 대상은 모듈 수준 Celery 인스턴스
# ──────────────────────────────────────────────────────────────────────
def test_command_starts_celery_worker() -> None:
    """② 명령이 `celery ... worker`다 — uvicorn(이미지 기본 CMD) 그대로 뜨면 소비자가 아니다."""
    command = _command(_worker())
    assert command[0] == "celery", command
    assert "worker" in command, command


def test_app_target_is_module_level_celery_instance_not_factory() -> None:
    """② `-A` 대상이 함수가 아니라 모듈 수준 변수(`= build_celery_app()` 호출 결과)다.

    팩토리 함수를 가리키면 Celery 5.6 CLI는 앱이 아닌 함수를 받아 기동 즉시 죽는다 —
    `restart: unless-stopped` 아래에서 크래시 루프를 돌며 작업은 계속 소비되지 않는다.
    """
    module, attr = _app_target(_command(_worker()))
    body = _module_tree(module).body

    defined_as_function = [
        node
        for node in body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == attr
    ]
    assert not defined_as_function, (
        f"`-A {module}:{attr}`의 {attr}가 함수다 — Celery CLI는 인스턴스를 기대한다"
        "(AttributeError: 'function' object has no attribute 'user_options')"
    )

    instance_assigns = [
        node
        for node in body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == attr for t in node.targets)
        and isinstance(node.value, ast.Call)
    ]
    assert instance_assigns, (
        f"`{module}`에 모듈 수준 `{attr} = <호출>` 할당이 없다 — `-A` 대상이 존재하지 않거나 "
        "호출 결과 인스턴스가 아니다"
    )
    call = instance_assigns[0].value
    assert isinstance(call, ast.Call)
    func = call.func
    func_name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    assert func_name in {"build_celery_app", "Celery"}, f"{attr}가 Celery 앱 생성 호출이 아니다"


# ──────────────────────────────────────────────────────────────────────
# ③ 동시성 1
# ──────────────────────────────────────────────────────────────────────
def test_concurrency_is_one_and_matches_code_constant() -> None:
    """③ `-c 1` — 코드의 WORKER_CONCURRENCY(앱 설정)와 기동 인자가 같은 값이다(이중 방어)."""
    command = _command(_worker())
    value = _option_value(command, "-c", "--concurrency")
    assert value == "1", f"워커 동시성이 1이 아니다: {value!r} — QUALITY는 GPU 단일 점유(03a §D.3)"
    assert _int_constant(_CELERY_APP_PY, "WORKER_CONCURRENCY") == 1


# ──────────────────────────────────────────────────────────────────────
# ④ 이미지 재사용·재시작
# ──────────────────────────────────────────────────────────────────────
def test_reuses_app_image_no_new_dockerfile() -> None:
    """④ app과 동일 이미지(불변 태그) — 새 Dockerfile·새 이미지 0."""
    assert str(_worker()["image"]) == str(_services()["app"]["image"])


def test_restarts_unless_stopped() -> None:
    """④ 크래시·재부팅 후 복귀한다 — 복귀하지 않으면 큐가 조용히 다시 소비자 없는 상태가 된다."""
    assert _worker().get("restart") == "unless-stopped"


def test_waits_for_healthy_redis() -> None:
    """④ 브로커(Redis)가 healthy가 된 뒤에 기동한다."""
    depends = _worker().get("depends_on") or {}
    assert isinstance(depends, dict) and depends.get("redis", {}).get("condition") == (
        "service_healthy"
    ), depends


# ──────────────────────────────────────────────────────────────────────
# ⑤ 같은 브로커·같은 Ollama
# ──────────────────────────────────────────────────────────────────────
def _env(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment") or {}
    assert isinstance(env, dict)
    return {str(k): "" if v is None else str(v) for k, v in env.items()}


def test_same_broker_url_as_app_with_interpolated_password() -> None:
    """⑤ 워커의 Redis URL이 app과 글자 그대로 같다 — 다르면 enqueue한 곳과 소비하는 곳이 갈린다."""
    worker_url = _env(_worker())["WHYMATH_REDIS_URL"]
    app_url = _env(_services()["app"])["WHYMATH_REDIS_URL"]
    assert worker_url == app_url
    assert "${WHYMATH_REDIS_PASSWORD" in worker_url, "비밀번호가 보간이 아니라 리터럴이다"


def test_same_ollama_host_as_app_and_host_gateway_mapped() -> None:
    """⑤ 워커도 컨테이너 밖 Ollama에 닿는다 — app과 같은 기본 주소 + host.docker.internal 매핑."""
    assert _env(_worker())["WHYMATH_OLLAMA_HOST"] == _env(_services()["app"])["WHYMATH_OLLAMA_HOST"]
    assert "host.docker.internal:host-gateway" in [str(h) for h in _worker().get("extra_hosts", [])]


# ──────────────────────────────────────────────────────────────────────
# ⑥ 최소 권한
# ──────────────────────────────────────────────────────────────────────
def test_env_is_allowlisted_no_unneeded_secrets() -> None:
    """⑥ 워커 env는 허용 목록 안이다 — DB·JWT·암호화 키·클라우드 키는 워커가 쓰지 않는다.

    (종단 실측: REDIS_URL·OLLAMA_HOST 두 변수만으로 enqueue→소비→결과 반환이 성립했다.)
    불필요한 시크릿이 하나 더 주입되면 워커 컨테이너 침해 시 피해 범위가 그만큼 넓어진다.
    """
    keys = set(_env(_worker()))
    assert _REQUIRED_ENV <= keys, f"필수 env 누락: {sorted(_REQUIRED_ENV - keys)}"
    unexpected = keys - _REQUIRED_ENV - _OPTIONAL_ENV
    assert (
        not unexpected
    ), f"허용 목록 밖 env: {sorted(unexpected)} — 필요하면 근거와 함께 목록을 고친다"


# ──────────────────────────────────────────────────────────────────────
# ⑦ 정상 종료 보장
# ──────────────────────────────────────────────────────────────────────
def test_stop_grace_period_outlasts_a_quality_generation() -> None:
    """⑦ 도커 기본 10s면 진행 중 QUALITY 생성이 SIGKILL로 끊기고 그 작업은 영구 pending이다."""
    raw = _worker().get("stop_grace_period")
    assert raw is not None, "stop_grace_period가 없다 — 도커 기본 10초가 적용된다"
    assert _grace_seconds(raw) >= _MIN_GRACE_SECONDS, raw


# ──────────────────────────────────────────────────────────────────────
# ⑧ 변별력 있는 헬스체크
# ──────────────────────────────────────────────────────────────────────
def _healthcheck_command() -> str:
    healthcheck = _worker().get("healthcheck") or {}
    assert healthcheck.get("disable") is not True, "헬스체크가 비활성화돼 있다"
    test = healthcheck.get("test")
    assert isinstance(test, list) and len(test) >= 2, test
    return " ".join(str(part) for part in test[1:])


def test_healthcheck_is_celery_ping_against_the_same_app() -> None:
    """⑧ 이미지의 HTTP 라이브니스 대신 같은 앱에 대한 `celery inspect ping`을 쓴다."""
    command = _command(_worker())
    target = _option_value(command, "-A", "--app")
    check = _healthcheck_command()
    assert "inspect ping" in check, check
    assert f"-A {target}" in check, f"헬스체크가 워커와 다른 앱을 본다: {check}"
    assert "/health/live" not in check, "워커는 HTTP 서버가 아니다"


def test_healthcheck_pings_only_its_own_node() -> None:
    """⑧ `-d celery@$$HOSTNAME` — 같은 브로커의 이웃 워커 응답으로 healthy가 되는 위장을 막는다.

    `-d` 없는 ping은 브로드캐스트라 어느 노드가 답해도 exit 0이다. 이 컨테이너의 워커가 죽었는데
    호스트 systemd 워커나 다른 환경 워커가 답하면 정상으로 보인다(2026-10-08 실측 오염 사례).
    """
    assert "-d celery@$$HOSTNAME" in _healthcheck_command()


# ──────────────────────────────────────────────────────────────────────
# ⑨ 깨진 기동 명령 부재 — 실행 가능한 문맥 전수
# ──────────────────────────────────────────────────────────────────────
# 팩토리를 `-A`에 직접 지정하는 형식. 산문이 이 형식을 *설명*할 때는 `-A`와 이름을 붙여 쓰지 않는다.
_FACTORY_AS_APP = re.compile(r"-A\s+\S*:build_celery_app\b|--app[= ]\S*:build_celery_app\b")

_EXECUTABLE_CONTEXTS = [
    "docker-compose.prod.yml",
    "infra/phaiakes9/systemd/whymath-worker.service",
    "infra/phaiakes9/OPERATIONS_24_7.md",
    "docs/architecture/deployment_cd_runbook.md",
    "src/backend/whymath_backend/l3/queue/celery_app.py",
    "src/backend/whymath_backend/l3/queue/tasks.py",
    "src/backend/whymath_backend/l3/queue/celery_job_queue.py",
]


@pytest.mark.parametrize("relative", _EXECUTABLE_CONTEXTS)
def test_no_factory_form_app_argument(relative: str) -> None:
    """⑨ 팩토리 형식 `-A ...:build_celery_app`가 없다 — 복사해 쓰면 워커가 기동 즉시 죽는다."""
    path = _ROOT / relative
    assert path.is_file(), f"스캔 대상이 없다(경로 이동? 가드가 공허해진다): {relative}"
    hits = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _FACTORY_AS_APP.search(line)
    ]
    assert not hits, f"{relative}에 깨진 기동 명령이 남아 있다: {hits}"
