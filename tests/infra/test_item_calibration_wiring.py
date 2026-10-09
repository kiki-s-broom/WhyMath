"""문항 난이도 보정 배치 스케줄 배선 실재성 동결 테스트 (hermetic — docker·DB 불요).

PB-10 acceptance ③: `l2/calibrate_items.py`는 CLI로 완비돼 있었지만 저장소 안에 그것을 부르는 곳이
0건이었다(`.github/workflows`·`docker-compose*.yml`·`infra/` 전수 grep 무일치). 응답이 쌓여도
`irt_difficulty_b`는 자동으로 채워지지 않는 상태였다 — "저장소에 존재함"과 "돌아감"은 다르다
(OPS-03/08/10/11·SEC-12 retention-purge 선례). 스케줄 좌석은 `docker-compose.prod.yml`의
`item-calibration` 서비스로 정했고(GitHub Actions cron은 prod DB에 닿지 못한다), 이 파일이 그 배선이
**실제로 보정을 쓰는 형태로** 박혀 있는지 기계 확인한다.

`test_deploy_artifacts.py`의 retention-purge 계약(⑧)이 "서비스가 있고 CLI를 부른다"까지만 보는 것과
달리, 여기서는 **셸 명령을 토큰 단위로 파싱**한다. 문자열 포함 검사만으로는 `--dry-run`을 붙인 서비스
(읽기 전용 측정 모드라 UPDATE를 하지 않는다)도 통과해 버린다 — 배선은 있는데 아무것도 쓰지 않는,
성공처럼 보이는 가장 나쁜 형태다. 금지 패턴 열거가 아니라 **구성된 명령의 인자 목록**을 본다.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.prod.yml"
_MODULE = "whymath_backend.l2.calibrate_items"
_MODULE_FILE = _ROOT / "src" / "backend" / "whymath_backend" / "l2" / "calibrate_items.py"
_SERVICE = "item-calibration"

# 배치 주기 상한 — 이보다 길면 "돌고 있다"는 말이 실질을 잃는다(한 달에 한 번 도는 보정은 응답 축적 속도를
# 못 따라간다). 하한은 두지 않는다(더 자주 도는 것은 비용 문제일 뿐 배선 결함이 아니다).
_MAX_INTERVAL_SECONDS = 7 * 86400


def _services() -> dict[str, Any]:
    data = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    services: dict[str, Any] = data["services"]
    # 스캔 0건은 실패다 — compose 파싱이 빈 서비스 맵을 주면 아래 모든 검사가 공허하게 통과한다.
    assert services, "docker-compose.prod.yml에서 서비스를 하나도 읽지 못했다"
    return services


def _service() -> dict[str, Any]:
    services = _services()
    assert _SERVICE in services, (
        f"docker-compose.prod.yml에 {_SERVICE} 서비스가 없다 — {_MODULE}를 부르는 스케줄이 사라지면 "
        "irt_difficulty_b는 응답이 쌓여도 자동으로 채워지지 않는다(PB-10 이전 상태)"
    )
    service: dict[str, Any] = services[_SERVICE]
    return service


def _shell_script(service: dict[str, Any]) -> str:
    """`sh -c "<script>"` 형태 command에서 스크립트 본문을 꺼낸다(형태가 다르면 실패)."""
    command = service.get("command")
    assert (
        isinstance(command, list) and command[:2] == ["sh", "-c"] and len(command) == 3
    ), f"command가 `[sh, -c, <script>]` 형태가 아니다: {command!r}"
    script = command[2]
    assert isinstance(script, str)
    return script


def _loop_body(script: str) -> tuple[list[list[str]], int]:
    """`while true; do <명령들>; sleep N; done`을 파싱해 (명령 토큰 목록들, sleep 초)를 돌려준다."""
    match = re.fullmatch(r"\s*while true;\s*do\s+(?P<body>.+?);\s*done\s*", script, re.DOTALL)
    assert match, f"`while true; do ...; done` 루프 형태가 아니다: {script!r}"
    commands: list[list[str]] = []
    interval: int | None = None
    for part in match.group("body").split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = shlex.split(part)
        if tokens[0] == "sleep":
            assert (
                len(tokens) == 2 and tokens[1].isdigit()
            ), f"sleep 인자가 정수 초가 아니다: {part!r}"
            interval = int(tokens[1])
        else:
            commands.append(tokens)
    assert (
        interval is not None
    ), f"루프에 sleep이 없다 — 쉬지 않고 도는 보정은 DB를 계속 친다: {script!r}"
    return commands, interval


def _calibration_command() -> list[str]:
    """루프 안에서 `python -m whymath_backend.l2.calibrate_items`를 부르는 명령의 토큰들.

    `|| exit 1` 같은 꼬리는 토큰으로 남으므로 `||` 앞까지만 자른다.
    """
    commands, _ = _loop_body(_shell_script(_service()))
    found = [c for c in commands if _MODULE in c]
    assert (
        len(found) == 1
    ), f"{_MODULE}를 정확히 1번 부르는 명령이어야 한다(발견 {len(found)}건): {commands!r}"
    tokens = found[0]
    return tokens[: tokens.index("||")] if "||" in tokens else tokens


def test_service_exists_and_calls_the_cli_via_python_dash_m() -> None:
    """① 서비스가 있고 `python -m <모듈>` 형태로 CLI를 부른다(경로 직접 실행·오타 모듈 거부)."""
    tokens = _calibration_command()
    assert tokens[:3] == [
        "python",
        "-m",
        _MODULE,
    ], f"호출 형태가 python -m {_MODULE}가 아니다: {tokens!r}"


def test_cli_invocation_does_not_use_dry_run() -> None:
    """② 구성된 명령 인자에 `--dry-run`이 없다 — 있으면 배선은 있으나 UPDATE가 영원히 0건이다."""
    tokens = _calibration_command()
    assert "--dry-run" not in tokens, (
        f"item-calibration이 --dry-run으로 돈다({tokens!r}) — 읽기 전용 측정 모드라 irt_difficulty_b가 "
        "영원히 채워지지 않는다. 측정은 harness.item_calibration_reach_report의 몫이다"
    )


def test_interval_is_bounded() -> None:
    """③ 루프 주기가 정수 초이고 상한 이내다 — 사실상 안 도는 주기를 거부한다."""
    _, interval = _loop_body(_shell_script(_service()))
    assert (
        0 < interval <= _MAX_INTERVAL_SECONDS
    ), f"sleep {interval}s — 상한 {_MAX_INTERVAL_SECONDS}s(7일)를 넘거나 0 이하다"


def test_failure_stops_the_container_so_restart_policy_retries() -> None:
    """④ CLI 실패가 루프에서 삼켜지지 않는다 — `|| exit 1`로 컨테이너를 내려 재시작 정책이 받는다.

    실패를 삼키고 `sleep`으로 넘어가면 보정이 하루 종일 죽어 있어도 컨테이너는 'running'이다(침묵 실패).
    """
    script = _shell_script(_service())
    assert re.search(
        rf"{re.escape(_MODULE)}\s*\|\|\s*exit 1\s*;", script
    ), f"CLI 실패 시 `|| exit 1`로 종료하지 않는다: {script!r}"
    assert _service().get("restart") == "unless-stopped"


def test_reuses_app_image_and_needs_only_the_database_url() -> None:
    """⑤ 신규 이미지 0(app과 동일 이미지) · 필요한 환경은 DB URL뿐(최소 권한)."""
    services = _services()
    assert str(services[_SERVICE]["image"]) == str(services["app"]["image"])
    env = services[_SERVICE].get("environment", {})
    assert "WHYMATH_DATABASE_URL" in env
    for forbidden in (
        "WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY",
        "WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY",
        "WHYMATH_JWT_SECRET_KEY",
    ):
        assert forbidden not in env, f"{_SERVICE}에 불필요한 시크릿이 주입됨: {forbidden}"


def test_database_url_is_not_trust_and_requires_password() -> None:
    """⑥ DB 접속이 fail-closed 비밀번호 참조(`${WHYMATH_DB_PASSWORD:?...}`)다 — trust 인증 금지."""
    url = str(_service()["environment"]["WHYMATH_DATABASE_URL"])
    assert "${WHYMATH_DB_PASSWORD:?" in url, f"비밀번호가 fail-closed 참조가 아니다: {url!r}"


def test_http_healthcheck_is_disabled() -> None:
    """⑦ HTTP 서버가 아니므로 이미지 HEALTHCHECK(8000 폴)를 끈다 — 안 끄면 영구 unhealthy 오판."""
    assert _service().get("healthcheck", {}).get("disable") is True


def test_depends_on_a_healthy_database() -> None:
    """⑧ DB가 healthy가 된 뒤 기동한다."""
    assert _service().get("depends_on", {}).get("db", {}).get("condition") == "service_healthy"


def test_cli_module_file_exists_and_exposes_main() -> None:
    """⑨ 서비스가 부르는 모듈이 저장소에 실재하고 `main()`을 노출한다(오타 모듈로 배선만 남는 것 방지)."""
    assert _MODULE_FILE.is_file(), f"{_MODULE_FILE} 부재"
    tree = ast.parse(_MODULE_FILE.read_text(encoding="utf-8"))
    mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert mains, f"{_MODULE}에 main()이 없다 — python -m 호출이 아무것도 실행하지 못한다"


def test_module_docstring_names_the_scheduling_seat() -> None:
    """⑩ CLI 모듈 docstring이 스케줄 좌석을 `item-calibration`으로 지목한다(예전 '외부 책임' 문구 재발 방지)."""
    text = _MODULE_FILE.read_text(encoding="utf-8")
    assert _SERVICE in text and "docker-compose.prod.yml" in text
    assert (
        "스케줄은 *외부*" not in text
    ), "'스케줄은 외부 책임' 문구가 돌아왔다 — 좌석이 저장소 안에 있다"


@pytest.mark.parametrize(
    "bad_script",
    [
        "while true; do python -m whymath_backend.l2.calibrate_items --dry-run || exit 1; sleep 86400; done",
    ],
)
def test_parser_discriminates_dry_run_from_real_run(bad_script: str) -> None:
    """⑪ 파서 자가검증 — `--dry-run` 변형이 실제로 토큰에 잡힌다(검사가 모든 입력에서 초록이 아님)."""
    commands, _ = _loop_body(bad_script)
    tokens = [c for c in commands if _MODULE in c][0]
    assert "--dry-run" in tokens
