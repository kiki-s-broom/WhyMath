"""backend 테스트를 **명시 경로**로 도는 CI 스텝이 설정 파일을 못 박는지 동결(OPS-61).

왜 이 테스트가 있는가 (2026-09-06 · PR #1003 Codex P1)
------------------------------------------------------
`src/backend/pyproject.toml`의 `[tool.pytest.ini_options]`는 `asyncio_mode="auto"`와
`addopts = [-ra, --strict-markers, --strict-config, --import-mode=importlib, --rootdir=../..]`
를 담는다. 그런데 pytest는 **위치 인자(테스트 경로)가 있으면** 그 인자의 공통조상을 상향
탐색해 rootdir/inifile을 정한다 — `cd src/backend && pytest ../../tests/backend/x.py`는
rootdir을 **저장소 루트**로 잡고, 루트 `pyproject.toml`에는 pytest 설정이 없으므로 위 ini가
**통째로 안 읽힌다**. asyncio_mode는 strict로 폴백하고 `--strict-markers`·`--strict-config`·
`--import-mode=importlib`도 전부 빠지는데, **화면상으로는 초록이라 아무도 모른다**.

실제로 그런 스텝이 3개 있었다(concept-reach 가드 · e2e 관통 · 앵커 A4). async 테스트가
없어서 우연히 통과하고 있었을 뿐, 마커 오타·import 모드 차이는 그대로 무방비였다.
`tests/backend/conftest.py`의 OPS-61 가드가 이 상태를 UsageError로 바꾸면서 그 3건이
**드러났다** — 가드가 없었으면 계속 조용했을 결함이다.

이 테스트는 그 3건을 고친 뒤, **같은 형태가 다시 들어오는 것**을 정적으로 막는다.
`tests/infra/test_anchor_e2e_nightly_wiring.py`(EOS-64)·`test_ci_concept_reach_guard_wiring.py`
(OPS-23)와 같은 사상 — "고쳤다"와 "다시 안 들어온다"는 다르다.

검증 계약 (변별력이 확인된 것만 — CLAUDE.md "변별력 없는 검증 스텝 금지")
------------------------------------------------------------------------
① ci.yml의 모든 `run` 스텝 중 **pytest에 `tests/backend/` 아래 위치 인자를 주는** 스텝은
   `-c`(또는 `--config-file`)로 설정 파일을 명시한다.
② 스캔이 공허하지 않다 — 판정 대상 스텝을 **하나도 못 찾으면 실패**한다(스캔 0건은 실패).
③ 파서가 위장하지 않는다 — ci.yml을 못 읽거나 jobs가 비면 예외.
④ 결함 주입으로 RED를 실증한다 — `-c`를 뗀 합성 스텝, `--config-file` 표기, `-m` 마커만
   주는(위치 인자 없는) 스텝, 옵션 값으로 경로가 오는 형태를 각각 구분하는지 확인한다.

`--ignore=../../tests/backend/l3`처럼 **옵션의 값**으로 경로가 오는 형태는 위치 인자가
아니므로 대상이 아니다(실측: rootdir이 cwd 기준으로 잡혀 ini가 정상 적용된다). 그래서
판정은 문자열 포함이 아니라 **토큰 파싱**으로 한다 — 문자열 검사였다면 이 스텝을 오탐한다.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YAML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

# 이 접두사로 시작하는 위치 인자 = backend 테스트를 명시 경로로 지목한 것.
# working-directory가 src/backend라 `../../tests/backend/...` 형태로 나타난다.
_BACKEND_TEST_PREFIXES: tuple[str, ...] = ("../../tests/backend/", "tests/backend/")

# 설정 파일을 못 박는 플래그(둘 다 pytest가 받는 동일 의미의 표기).
_CONFIG_FLAGS: tuple[str, ...] = ("-c", "--config-file")

# 값을 뒤 토큰으로 받는 pytest 옵션 — 그 값은 위치 인자가 아니다.
# (`--ignore=X` 같은 `=` 결합 표기는 토큰 자체가 `-`로 시작하므로 별도 처리 불요.)
_VALUE_TAKING_FLAGS: frozenset[str] = frozenset(
    {"-c", "--config-file", "-m", "-k", "-p", "-n", "--rootdir", "--ignore", "--deselect", "-o"}
)


def _extract_jobs(spec: Any, source: str) -> dict[str, Any]:
    """스펙에서 jobs 매핑을 꺼낸다 — 공백/비매핑이면 예외(계약 ③: 파서 무력화 ≠ 통과)."""
    if not isinstance(spec, dict):
        raise AssertionError(f"{source}: 워크플로 YAML이 매핑으로 파싱되지 않았다.")
    jobs = spec.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise AssertionError(f"{source}: jobs 블록이 비었다 — 파서가 배선을 읽지 못하는 상태다.")
    return jobs


def _load_ci_jobs() -> dict[str, Any]:
    """ci.yml을 파싱해 jobs를 돌려준다 — 못 읽거나 비면 예외(계약 ③)."""
    if not _CI_YAML.is_file():
        raise AssertionError(f"{_CI_YAML}: CI 워크플로 파일이 없다 — 배선을 읽을 수 없다.")
    spec = yaml.safe_load(_CI_YAML.read_text(encoding="utf-8"))
    return _extract_jobs(spec, str(_CI_YAML))


def _iter_run_scripts(jobs: Mapping[str, Any]) -> Iterator[tuple[str, str, str]]:
    """(잡 키, 스텝 이름, run 스크립트)를 흘린다."""
    for job_key, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict) and step.get("run"):
                yield job_key, str(step.get("name") or "(이름 없음)"), str(step["run"])


def _pytest_invocations(script: str) -> list[list[str]]:
    """`run` 스크립트에서 pytest 호출의 인자 토큰 목록을 뽑는다.

    줄 단위로 훑되 `\\` 줄바꿈은 이어 붙인다. 반환값은 `pytest` **다음** 토큰들이다.
    """
    joined = script.replace("\\\n", " ")
    invocations: list[list[str]] = []
    for line in joined.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True)
        except ValueError:  # 따옴표가 안 닫힌 셸 조각 — 판정 대상이 아니다
            continue
        for i, token in enumerate(tokens):
            if Path(token).name == "pytest" and not token.startswith("-"):
                invocations.append(tokens[i + 1 :])
                break
    return invocations


def _positional_args(tokens: list[str]) -> list[str]:
    """옵션과 그 값을 걷어내고 남은 **위치 인자**만 돌려준다."""
    positional: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if token in _VALUE_TAKING_FLAGS:
                skip_next = True
            continue
        positional.append(token)
    return positional


def _targets_backend_tests(positional: list[str]) -> bool:
    return any(arg.startswith(_BACKEND_TEST_PREFIXES) for arg in positional)


def _pins_config(tokens: list[str]) -> bool:
    return any(
        token in _CONFIG_FLAGS or token.startswith(tuple(f"{f}=" for f in _CONFIG_FLAGS))
        for token in tokens
    )


def config_pin_violations(jobs: Mapping[str, Any]) -> tuple[list[str], int]:
    """위반 목록과 **판정 대상 스텝 수**를 함께 돌려준다(계약 ②: 분모가 보여야 한다)."""
    violations: list[str] = []
    considered = 0
    for job_key, step_name, script in _iter_run_scripts(jobs):
        for tokens in _pytest_invocations(script):
            if not _targets_backend_tests(_positional_args(tokens)):
                continue
            considered += 1
            if not _pins_config(tokens):
                violations.append(
                    f"{job_key} / {step_name}: backend 테스트를 명시 경로로 도는데 "
                    f"`-c pyproject.toml`이 없다 — src/backend의 pytest ini가 통째로 "
                    f"안 읽힌다(OPS-61). 인자: {tokens}"
                )
    return violations, considered


def test_explicit_path_backend_pytest_steps_pin_config() -> None:
    """계약 ①② — 실 ci.yml. 대상이 0건이면 공허한 통과이므로 함께 실패시킨다."""
    violations, considered = config_pin_violations(_load_ci_jobs())
    assert considered > 0, (
        "backend 테스트를 명시 경로로 도는 pytest 스텝을 하나도 찾지 못했다 — "
        "스캔이 공허하다(경로 표기·워크플로 구조가 바뀌었을 수 있다). "
        "0건 통과와 측정 실패는 같은 색이면 안 된다."
    )
    assert violations == [], "OPS-61 설정 미고정 위반:\n" + "\n".join(f"- {v}" for v in violations)


def _synthetic(run: str) -> dict[str, Any]:
    """결함 주입용 합성 **jobs 매핑**(스펙 전체가 아니다 — `config_pin_violations`는 jobs를 받는다).

    처음 작성할 때 여기서 스펙 전체(`{"jobs": ...}`)를 돌려줬고, 그러면 파서가 스텝을 하나도
    못 봐서 음성 대조(`considered == 0`)가 **공허하게 통과**했다. 결함 주입 테스트가 RED를
    내 준 덕에 잡혔다 — 이 주석은 그 형태를 다시 만들지 않기 위한 표식이다.
    """
    return {"j": {"steps": [{"name": "s", "run": run}]}}


def test_detects_missing_config_flag() -> None:
    """결함 주입 ⓐ — `-c`를 떼면 RED가 나야 한다(이 테스트의 존재 이유)."""
    violations, considered = config_pin_violations(
        _synthetic("python -m pytest ../../tests/backend/harness/test_x.py")
    )
    assert considered == 1
    assert violations != []


def test_accepts_config_flag_forms() -> None:
    """양성 대조 — `-c`·`--config-file`·`=` 결합 표기를 모두 준수로 받는다(과잉 차단 금지)."""
    for form in (
        "-c pyproject.toml",
        "--config-file pyproject.toml",
        "--config-file=pyproject.toml",
    ):
        violations, considered = config_pin_violations(
            _synthetic(f"python -m pytest {form} ../../tests/backend/harness/test_x.py")
        )
        assert considered == 1, form
        assert violations == [], form


def test_option_value_paths_are_not_positional() -> None:
    """음성 대조 — `--ignore=<경로>`·`-m` 마커만 주는 스텝은 대상이 아니다.

    문자열 포함 검사였다면 여기서 오탐한다. 토큰 파싱이라 구분된다.
    """
    for run in (
        "pytest -m integration --ignore=../../tests/backend/l3",
        "pytest -m integration",
        "pytest --deselect ../../tests/backend/api/test_x.py::test_y -m integration",
    ):
        _, considered = config_pin_violations(_synthetic(run))
        assert considered == 0, run
        # 변별력 확인 — 같은 스텝에 **위치 인자**를 하나 붙이면 대상이 되어야 한다.
        # 이게 없으면 파서가 아무것도 못 보는 상태에서도 위 단언이 통과한다(공허한 0건).
        _, with_positional = config_pin_violations(
            _synthetic(f"{run} ../../tests/backend/harness/test_x.py")
        )
        assert with_positional == 1, run


def test_parser_refuses_to_pass_vacuously() -> None:
    """계약 ③ — 빈 스펙/비매핑은 통과가 아니라 예외. 실제 추출 함수를 그대로 친다."""
    for bad in ({}, {"jobs": {}}, {"jobs": None}, [], None, "jobs: {}"):
        with pytest.raises(AssertionError):
            _extract_jobs(bad, "합성")
