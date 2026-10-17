"""[OPS-11·OPS-12] 테스트·하네스 디렉터리의 **lint/format 배선** 동결.

왜 이 테스트가 있는가
--------------------
OPS-03이 `infra-contracts` 잡으로 `tests/infra`의 *실행*을 배선했지만, **코드 품질 축은
여전히 무배선이었다** — backend 잡은 `../../tests/backend`만 lint하고 이 잡엔 ruff/black
스텝이 없었다. 실측(2026-07-27): 배선 직전 `black --check`가 `test_backup_script.py`
1건에서 실패하고 있었고, 아무도 알지 못했다.

같은 구멍이 `harness-integrity` 잡에도 있었다(OPS-12) — `tests/harness`·`scripts/harness`를
lint하는 잡이 하나도 없었고, 실측(2026-07-27) 배선 직전 ruff F541 2건(test_cli.py) +
black --check 17파일이 실패 상태였다. 하네스는 backlog 대장을 판정하는 코드라
"검사하는 자를 아무도 검사하지 않는" 구멍이 특히 아프다.

이것은 이 프로젝트에서 **반복되는 부류**다 — "장치는 있는데 일부만 배선됨"(CLAUDE.md
"검증 장치를 만들고 배선 확인 없이 완료 선언 금지"가 겨냥하는 형태). 새 lint 배선을
추가하면 `_WIRINGS`에 (잡, 대상 경로들) 한 줄을 추가해 같은 계약으로 동결하라.

**이 파일만으로는 부족하다** (OPS-13): 여기 표는 *등재된 것*의 품질만 본다 — 등재 자체를
빠뜨리면 못 잡는다. 누락 축은 `test_lint_coverage.py`가 소스에서 출발해 전수로 검사한다.
두 파일은 역할이 갈리므로 계약을 중복시키지 않는다(품질 ↔ 누락).

검증 계약
--------
① 각 잡에 ruff·black 스텝이 **둘 다** 있다
② black 스텝이 저장소 표준 `--line-length 100` + `--check`를 쓴다 (규칙이 갈리면 무의미)
③ 두 스텝이 선언된 대상 경로 **전부**를 검사한다 (다른 경로를 검사하는 위장 차단)
④ 파서가 위장하지 않는다 — 워크플로/잡을 못 찾으면 "위반 0 통과"가 아니라 **실패**
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

# (잡 이름, 그 잡이 lint해야 하는 대상 경로들) — 배선 추가 시 여기에 등재해 동결한다.
_WIRINGS: list[tuple[str, tuple[str, ...]]] = [
    ("infra-contracts", ("tests/infra", "infra", "conftest.py")),  # OPS-11 · OPS-13
    # HARN-206(2026-09-29) — tools/ 확대: 데스크톱 앱의 픽스처 생성기(`tools/work-graph-desktop/
    # fixtures/make_fixture.py`)가 어떤 lint에도 안 잡혀 `test_lint_coverage`가 red였다.
    ("harness-integrity", ("scripts", "tests/harness", "tools")),  # OPS-12 · OPS-13 · HARN-206
    ("data-pipeline", ("tests/data_pipeline",)),  # OPS-14(OPS-13 허용목록 상환)
]
_WIRING_IDS = [job for job, _ in _WIRINGS]


def _job_run_scripts(job_key: str) -> list[str]:
    """해당 잡의 모든 `run` 스크립트. 못 찾으면 실패(위장 차단)."""
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — lint 배선을 확인할 수 없다.")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    jobs = (spec or {}).get("jobs") or {}
    if job_key not in jobs:
        raise AssertionError(
            f"ci.yml에 `{job_key}` 잡이 없다 — 잡을 개명했다면 이 테스트의 `_WIRINGS`도 "
            "함께 고쳐라(그러지 않으면 lint 배선이 조용히 사라진다)."
        )
    steps = (jobs[job_key] or {}).get("steps") or []
    scripts = [str(s.get("run", "")) for s in steps if isinstance(s, dict) and s.get("run")]
    if not scripts:
        raise AssertionError(f"`{job_key}` 잡에 `run` 스텝이 하나도 없다.")
    return scripts


def _step_invoking(tool: str, job_key: str) -> str:
    """해당 도구를 *검사 목적*으로 실행하는 스텝을 찾는다(설치 명령은 제외)."""
    for script in _job_run_scripts(job_key):
        if "pip install" in script:
            continue
        if f"-m {tool}" in script or script.strip().startswith(tool):
            return script
    return ""


@pytest.mark.parametrize(("job_key", "targets"), _WIRINGS, ids=_WIRING_IDS)
def test_ruff_step_exists(job_key: str, targets: tuple[str, ...]) -> None:
    """계약 ① — ruff 스텝이 없으면 대상 디렉터리의 정적 위반이 CI를 통과한다."""
    assert _step_invoking("ruff", job_key), (
        f"`{job_key}` 잡에 ruff 스텝이 없다 — {', '.join(targets)}는 어떤 잡도 lint하지 "
        "않게 된다 (backend 잡은 tests/backend만 본다)."
    )


@pytest.mark.parametrize(("job_key", "targets"), _WIRINGS, ids=_WIRING_IDS)
def test_black_step_exists(job_key: str, targets: tuple[str, ...]) -> None:
    """계약 ① — black 스텝이 없으면 포맷 드리프트가 조용히 쌓인다(실측 선례 18파일)."""
    assert _step_invoking("black", job_key), f"`{job_key}` 잡에 black 스텝이 없다."


@pytest.mark.parametrize(("job_key", "targets"), _WIRINGS, ids=_WIRING_IDS)
def test_black_uses_repo_standard_line_length(job_key: str, targets: tuple[str, ...]) -> None:
    """계약 ② — 다른 잡과 다른 규칙으로 검사하면 통과해도 의미가 없다."""
    script = _step_invoking("black", job_key)
    assert script, f"`{job_key}` black 스텝 부재(위 테스트 참조)"
    assert (
        "--line-length 100" in script
    ), f"`{job_key}` black 스텝이 저장소 표준 `--line-length 100`을 쓰지 않는다: {script.strip()!r}"
    assert (
        "--check" in script
    ), "black이 `--check` 없이 실행되면 CI에서 파일을 고쳐버린다(게이트 아님)."


@pytest.mark.parametrize(("job_key", "targets"), _WIRINGS, ids=_WIRING_IDS)
def test_both_steps_cover_declared_targets(job_key: str, targets: tuple[str, ...]) -> None:
    """계약 ③ — 선언된 대상 일부만(또는 다른 경로를) 검사하며 통과하는 위장을 차단한다."""
    for tool in ("ruff", "black"):
        script = _step_invoking(tool, job_key)
        assert script, f"`{job_key}` {tool} 스텝 부재"
        for target in targets:
            assert (
                target in script
            ), f"`{job_key}` {tool} 스텝이 `{target}`를 대상으로 하지 않는다: {script.strip()!r}"


def test_parser_fails_loudly_on_unknown_job() -> None:
    """계약 ④ — 잡을 못 찾으면 조용한 통과가 아니라 예외여야 한다."""
    with pytest.raises(AssertionError, match="잡이 없다"):
        _job_run_scripts("__nonexistent_job__")
