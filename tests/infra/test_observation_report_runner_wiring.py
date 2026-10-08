"""[OPS-19] 관측 리포트 러너 — 배선 실재성 동결 (`test_weekly_metrics_cron_wiring.py` 동형).

러너 모듈이 저장소에 있는 것과, 그것이 **실제로 도는 곳에 물려 있는가**는 다른 질문이다
("저장소에 존재함"과 "돌아감"은 다르다 — OPS-03·08·10·11 계열). 이 파일은 파일만 읽는다
(`infra-contracts` 잡은 백엔드를 설치하지 않으므로 러너·감사기를 import하지 않는다). 러너 목록과
감사기 면제 사전의 대조는 `tests/backend/ops/test_observation_report_registry.py`가 맡는다.

검증 계약 (각 항목은 결함 주입으로 RED가 되는 것만)
---------------------------------------------------
① `ci.yml` `harness-integrity` 잡에 `python -m …observation_report_runner --class ci` 스텝이 있고
   `continue-on-error`가 없다(있으면 리포트가 못 돌아도 잡이 초록 — 이 태스크가 고치려는 위장).
② 그 스텝은 `ci` 부류만 돈다 — DB 필요 부류(`db`·`checkout_db`)가 섞이면 DB 없는 CI에서
   "접속 실패"가 매 PR마다 나거나 삼켜져 "0건"이 된다(acceptance ③).
③ 산출물 업로드 스텝이 `if: always()`다 — 실패한 실행의 증거가 가장 필요하다.
④ `docker-compose.prod.yml`의 `observation-reports` 서비스가 `app`과 같은 이미지로
   `--class db`만 돌고, 부류 혼합·재기동 폭주·학생 데이터 키 누출이 없다.
⑤ 이 기능의 테스트 디렉터리(`tests/backend/ops`·`tests/infra`)가 CI의 실제 pytest 실행에
   도달한다 — `test_test_suite_wiring.py`의 `Wiring`/`_all_wirings`를 재사용한다(새 파서 금지).

의도적으로 검증하지 않는 것 (정직한 공백)
-----------------------------------------
- compose 서비스가 **실제로 기동·실행되는지**는 보지 않는다(Docker 없는 CI — 정의 계약까지만).
  러너 자체의 실행 계약은 `tests/backend/ops/test_observation_report_runner.py`와 실 PG 실측이 맡는다.
- 7일 주기 `sleep 604800`이 실제로 7일 뒤 재실행하는지는 시간이 걸려 못 본다 — 값의 존재만 고정한다.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.infra.test_test_suite_wiring import _REPO_ROOT, _TESTS_ROOT, _all_wirings

_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_COMPOSE = _REPO_ROOT / "docker-compose.prod.yml"
_RUNNER_SRC = (
    _REPO_ROOT / "src" / "backend" / "whymath_backend" / "ops" / "observation_report_runner.py"
)
_RUNNER_MODULE = "whymath_backend.ops.observation_report_runner"
_CI_JOB = "harness-integrity"
_SERVICE = "observation-reports"
# 학생 데이터 암호화 키 계열은 `app` 밖으로 새지 않는다(tests/infra/test_prod_compose_student_data_keys.py).
_ALLOWED_ENV = {"WHYMATH_DATABASE_URL"}


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError(f"{path}를 매핑으로 읽지 못했다")
    return data


def _ci_steps(spec: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = spec.get("jobs")
    if not jobs or _CI_JOB not in jobs:
        raise AssertionError(f"ci.yml에 {_CI_JOB} 잡이 없다")
    steps = jobs[_CI_JOB].get("steps")
    if not steps:
        raise AssertionError(f"{_CI_JOB} 잡에 steps가 없다")
    return list(steps)


def _ci_violations(spec: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    steps = _ci_steps(spec)
    runs = [s for s in steps if _RUNNER_MODULE in str(s.get("run", ""))]
    if len(runs) != 1:
        return [f"러너 스텝이 {len(runs)}개다(정확히 1개여야 한다)"]
    run_step = runs[0]
    command = str(run_step["run"])
    if f"python -m {_RUNNER_MODULE}" not in command:
        problems.append("`python -m`이 아니다(실행기 단독 호출 금지)")
    if "--class ci" not in command:
        problems.append("`--class ci`가 없다")
    for forbidden in ("--class db", "--class checkout_db"):
        if forbidden in command:
            problems.append(f"DB 필요 부류 혼입: {forbidden}")
    if run_step.get("continue-on-error"):
        problems.append("러너 스텝이 continue-on-error — 리포트가 못 돌아도 초록이 된다")
    if "--out" not in command:
        problems.append("--out이 없다 — 산출물이 남지 않는다")
    uploads = [
        s
        for s in steps
        if str(s.get("uses", "")).startswith("actions/upload-artifact")
        and "observation-reports" in str((s.get("with") or {}).get("name", ""))
    ]
    if len(uploads) != 1:
        problems.append(f"산출물 업로드 스텝이 {len(uploads)}개다(정확히 1개여야 한다)")
    elif "always()" not in str(uploads[0].get("if", "")):
        problems.append("업로드 스텝이 if: always()가 아니다 — 실패한 실행의 증거가 사라진다")
    return problems


def _command_text(service: dict[str, Any]) -> str:
    command = service.get("command", [])
    return " ".join(command) if isinstance(command, list) else str(command)


def _compose_violations(compose: dict[str, Any]) -> list[str]:
    services = compose.get("services") or {}
    if _SERVICE not in services:
        return [f"{_SERVICE} 서비스가 없다"]
    svc = services[_SERVICE]
    problems: list[str] = []
    if svc.get("image") != services["app"].get("image"):
        problems.append("`app`과 다른 이미지 — 새 이미지/Dockerfile 금지(신규 로직 0)")
    command = _command_text(svc)
    if f"python -m {_RUNNER_MODULE}" not in command:
        problems.append("명령이 러너를 `python -m`으로 호출하지 않는다")
    if "--class db" not in command:
        problems.append("`--class db`가 없다")
    for forbidden in ("--class ci", "--class checkout_db"):
        if forbidden in command:
            problems.append(
                f"부류 혼입: {forbidden} — checkout_db는 이미지에 tests/가 없어 파일 부재가 낮은 수치로 읽힌다"
            )
    if "sleep 604800" not in command:
        problems.append("성공 시 7일 주기(sleep 604800)가 없다")
    if "sleep 3600" not in command:
        problems.append("실패 시 1시간 재시도(sleep 3600)가 없다 — DB 일시 장애가 7일 방치된다")
    if "exit 1" in command:
        problems.append("`exit 1` — 실패 시 컨테이너가 죽어 재기동 루프가 매번 10개를 다시 돈다")
    if svc.get("restart") != "unless-stopped":
        problems.append("restart != unless-stopped")
    if (svc.get("healthcheck") or {}).get("disable") is not True:
        problems.append(
            "healthcheck가 비활성화되지 않았다 — 도커가 8000 무응답을 unhealthy로 오판한다"
        )
    env_keys = set((svc.get("environment") or {}).keys())
    if env_keys != _ALLOWED_ENV:
        problems.append(
            f"환경변수 {sorted(env_keys)} — 허용은 {sorted(_ALLOWED_ENV)}뿐이다(키 누출 금지)"
        )
    depends = (svc.get("depends_on") or {}).get("db") or {}
    if depends.get("condition") != "service_healthy":
        problems.append("db service_healthy에 의존하지 않는다")
    return problems


# ── 실제 파일 계약 ────────────────────────────────────────────────────────────


def test_runner_source_exists() -> None:
    assert _RUNNER_SRC.is_file()


def test_ci_step_and_upload_are_wired_for_real() -> None:
    """①②③ 실제 ci.yml."""
    problems = _ci_violations(_load(_CI))
    assert not problems, "\n".join(problems)


def test_compose_service_is_wired_for_real() -> None:
    """④ 실제 docker-compose.prod.yml."""
    problems = _compose_violations(_load(_COMPOSE))
    assert not problems, "\n".join(problems)


def test_new_tests_are_reached_by_a_ci_pytest_run() -> None:
    """⑤ 이 기능의 테스트가 CI에서 실제로 도는 디렉터리에 있다(작성만 되고 안 도는 상태 금지)."""
    wirings = _all_wirings()
    assert wirings, "CI pytest 배선을 하나도 못 찾았다 — 파서가 위장하고 있다"
    for directory in (_TESTS_ROOT / "backend" / "ops", _TESTS_ROOT / "infra"):
        assert directory.is_dir(), directory
        assert any(w.covers(directory) for w in wirings), f"{directory}를 수집하는 CI 실행이 없다"


# ── 판정 함수의 변별력: 정상 대조 + 결함 주입 ─────────────────────────────────


@pytest.fixture
def ci_spec() -> dict[str, Any]:
    return _load(_CI)


@pytest.fixture
def compose_spec() -> dict[str, Any]:
    return _load(_COMPOSE)


def _runner_step(spec: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in _ci_steps(spec) if _RUNNER_MODULE in str(s.get("run", "")))


def test_control_real_files_pass_both_judges(
    ci_spec: dict[str, Any], compose_spec: dict[str, Any]
) -> None:
    """양성 대조 — 무차별 실패하는 판정기가 아님을 보인다."""
    assert _ci_violations(ci_spec) == []
    assert _compose_violations(compose_spec) == []


def test_defect_removed_ci_step_is_detected(ci_spec: dict[str, Any]) -> None:
    steps = ci_spec["jobs"][_CI_JOB]["steps"]
    ci_spec["jobs"][_CI_JOB]["steps"] = [
        s for s in steps if _RUNNER_MODULE not in str(s.get("run", ""))
    ]
    assert any("러너 스텝이 0개" in p for p in _ci_violations(ci_spec))


def test_defect_continue_on_error_is_detected(ci_spec: dict[str, Any]) -> None:
    _runner_step(ci_spec)["continue-on-error"] = True
    assert any("continue-on-error" in p for p in _ci_violations(ci_spec))


@pytest.mark.parametrize("extra", ["--class db", "--class checkout_db"])
def test_defect_db_class_mixed_into_ci_is_detected(ci_spec: dict[str, Any], extra: str) -> None:
    step = _runner_step(ci_spec)
    step["run"] = str(step["run"]) + f"\npython -m {_RUNNER_MODULE} {extra} --out /tmp/x"
    assert any("DB 필요 부류 혼입" in p for p in _ci_violations(ci_spec))


def test_defect_bare_python_is_detected(ci_spec: dict[str, Any]) -> None:
    step = _runner_step(ci_spec)
    step["run"] = str(step["run"]).replace(f"python -m {_RUNNER_MODULE}", f"{_RUNNER_MODULE}")
    assert any("python -m" in p for p in _ci_violations(ci_spec))


def test_defect_upload_not_always_is_detected(ci_spec: dict[str, Any]) -> None:
    for step in _ci_steps(ci_spec):
        if str(step.get("uses", "")).startswith("actions/upload-artifact") and "observation" in str(
            (step.get("with") or {}).get("name", "")
        ):
            step.pop("if", None)
    assert any("always()" in p for p in _ci_violations(ci_spec))


def test_defect_missing_job_fails_loudly(ci_spec: dict[str, Any]) -> None:
    ci_spec["jobs"].pop(_CI_JOB)
    with pytest.raises(AssertionError, match="잡이 없다"):
        _ci_violations(ci_spec)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda s: s.__setitem__("image", "whymath-backend:other"), "다른 이미지"),
        (lambda s: s.__setitem__("command", ["sh", "-c", "echo hi"]), "러너를"),
        (
            lambda s: s.__setitem__(
                "command",
                [
                    "sh",
                    "-c",
                    f"python -m {_RUNNER_MODULE} --class checkout_db --out /tmp/o; sleep 604800; sleep 3600",
                ],
            ),
            "부류 혼입",
        ),
        (
            lambda s: s.__setitem__(
                "command",
                [
                    "sh",
                    "-c",
                    f"python -m {_RUNNER_MODULE} --class db --out /tmp/o || exit 1; sleep 604800; sleep 3600",
                ],
            ),
            "exit 1",
        ),
        (lambda s: s.__setitem__("restart", "no"), "restart"),
        (lambda s: s.pop("healthcheck"), "healthcheck"),
        (
            lambda s: s["environment"].__setitem__("WHYMATH_STUDENT_DATA_KEY", "x"),
            "키 누출",
        ),
        (lambda s: s.pop("depends_on"), "service_healthy"),
    ],
    ids=[
        "image",
        "no-runner",
        "mixed-class",
        "crash-loop",
        "restart",
        "healthcheck",
        "key-leak",
        "depends",
    ],
)
def test_defect_compose_variants_are_detected(
    compose_spec: dict[str, Any], mutate: Any, expected: str
) -> None:
    mutated = copy.deepcopy(compose_spec)
    mutate(mutated["services"][_SERVICE])
    assert any(expected in p for p in _compose_violations(mutated)), _compose_violations(mutated)


def test_defect_missing_service_is_detected(compose_spec: dict[str, Any]) -> None:
    compose_spec["services"].pop(_SERVICE)
    assert _compose_violations(compose_spec) == [f"{_SERVICE} 서비스가 없다"]
