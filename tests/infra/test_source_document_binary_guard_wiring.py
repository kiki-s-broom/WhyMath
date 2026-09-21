"""[LIC-07 ④] 저작권 원본 차단 가드의 **배선 실재성** 동결.

`scripts/ops/check_source_document_binaries.py`가 저장소에 존재하는 것과 CI가 실제로 그것을
실행하는 것은 다르다(CLAUDE.md "검증 장치를 만들고 배선 확인 없이 완료 선언 금지" — 이
저장소에서 반복 발생한 부류다: `tests/infra` 199건 미실행 OPS-03 · required check 미강제
OPS-08 · lint 잡 부재 OPS-11). 이 테스트가 없으면 `ci.yml`에서 스텝이 조용히 지워져도 아무
신호가 나지 않는다 — 하필 이 가드가 막으려는 사고(원본 문서가 아무 신호 없이 들어옴)와
같은 형태로 가드 자신이 사라지는 것이다.

검증 계약
--------
① `policy-guard` 잡에 이 스크립트를 실행하는 `run` 스텝이 실재한다.
② 그 잡이 `needs: changes` 경로 필터에 종속되지 않는다 — PDF 하나만 추가하는 PR은
   backend/mobile/web 어느 필터에도 안 걸려 잡이 skip되고, GitHub는 **skipped를 required
   check 충족으로 계상**한다. 즉 필터에 종속되는 순간 이 가드는 자기가 막아야 할 바로 그
   PR에서 돌지 않는다.
③ 파서가 위장하지 않는다 — 워크플로/잡을 못 찾으면 "위반 0 통과"가 아니라 **실패**.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_GUARD_PATH = _REPO_ROOT / "scripts" / "ops" / "check_source_document_binaries.py"
_JOB_KEY = "policy-guard"
_INVOCATION = "scripts/ops/check_source_document_binaries.py"


@pytest.fixture(scope="module")
def policy_guard_job() -> dict[str, Any]:
    """③ 못 찾으면 통과가 아니라 실패."""
    assert _CI_PATH.is_file(), f"ci.yml 부재: {_CI_PATH}"
    workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "ci.yml 파싱 실패 — 통과로 위장하지 않는다"
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and jobs, "ci.yml에 jobs가 없다"
    job = jobs.get(_JOB_KEY)
    assert isinstance(job, dict), f"'{_JOB_KEY}' 잡이 없다 — 가드가 배선될 자리 자체가 사라졌다"
    return job


def test_guard_script_exists_and_is_executable_by_python(policy_guard_job) -> None:
    assert _GUARD_PATH.is_file(), f"가드 스크립트 부재: {_GUARD_PATH}"


def test_ci_runs_the_guard(policy_guard_job) -> None:
    """① CI가 실제로 이 스크립트를 실행한다."""
    steps = policy_guard_job.get("steps")
    assert isinstance(steps, list) and steps, "policy-guard 잡에 steps가 없다"
    runs = [str(s.get("run", "")) for s in steps if isinstance(s, dict)]
    assert any(_INVOCATION in r for r in runs), (
        f"policy-guard 잡이 '{_INVOCATION}'를 실행하지 않는다 — 스크립트가 저장소에 "
        "있기만 하고 돌지 않으면 보호가 아니다."
    )


def test_guard_job_is_not_gated_by_path_filter(policy_guard_job) -> None:
    """② 경로 필터에 종속되면 PDF만 추가한 PR에서 skip된다(그리고 skip은 충족으로 계상된다)."""
    needs = policy_guard_job.get("needs")
    needs_list = [needs] if isinstance(needs, str) else list(needs or [])
    assert "changes" not in needs_list, (
        "policy-guard가 `needs: changes`에 종속됐다 — 원본 PDF 하나만 추가하는 PR은 "
        "어떤 경로 필터에도 걸리지 않아 잡이 skip되고, GitHub는 skipped를 required check "
        "충족으로 센다. 이 가드가 존재하는 바로 그 상황에서 돌지 않게 된다."
    )
    assert (
        "if" not in policy_guard_job
    ), "policy-guard에 조건부 실행(`if`)이 붙었다 — 상시 실행이어야 한다."
