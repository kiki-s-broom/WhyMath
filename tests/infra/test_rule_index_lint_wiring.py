"""HARN-121 ④ — 규칙 인덱스 린트의 **집행 지점** 동결.

"저장소에 존재함"과 "돌아감"은 다르다. 이 저장소는 만든 검증 장치가 어느 잡도
실행하지 않던 상태를 반복해 겪었다(OPS-03 `tests/infra` 199건 미실행 · OPS-08
required check 미강제 · OPS-11 lint 잡 부재). 그래서 린트를 만든 것과 별개로,
그것이 **CI에서 실제로 실행되는지**를 여기서 기계로 고정한다.

검증 계약 (각 항목은 결함 주입으로 변별력을 확인한 것만)
-------------------------------------------------------
① `rules lint` 를 도는 스텝이 실재한다.
② `rules render --check` 도 같이 돈다 — 린트만 있으면 문서가 대장과 어긋난 채
   통과한다(문서는 렌더 결과다).
③ 그 스텝이 `continue-on-error: true` 가 아니다(fail-open이면 깨져도 초록).
④ 스텝이 **하네스 런타임을 설치하는 잡** 안에 있다 — 잡을 잘못 고르면 스텝은
   존재하는데 파이썬이 없어 상시 실패하거나, 경로가 달라 아무것도 안 본다.
⑤ 파서가 위장하지 않는다 — 못 읽거나 jobs가 비면 통과가 아니라 실패.

의도적으로 검증하지 않는 것 (정직한 공백)
--------------------------------------
- **린트의 판정 정확성**은 `tests/harness/test_rule_index.py`(L1~L6 주입 56건)가
  담당한다. 여기서 보는 것은 "그 린트가 CI에서 도는가"뿐이다.
- **GitHub가 실제로 이 잡을 실행했는가**는 우리 코드가 볼 수 없다.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

_LINT_CMD = "rules lint"
_RENDER_CHECK_CMD = "rules render --check"
_HARNESS_CLI = "scripts/harness/backlog.py"
# 하네스 CLI가 이미 돌고 있는 잡 — 린트가 여기 있어야 런타임·경로가 맞는다.
_EXPECTED_JOB = "harness-integrity"


def _load_workflow() -> dict[str, Any]:
    if not _WORKFLOW_PATH.is_file():
        raise AssertionError(f"{_WORKFLOW_PATH} 이(가) 없다 — 판정 불가(위장 통과 금지).")
    spec: Any = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("ci.yml에 jobs가 없다 — 파싱이 위장 통과할 수 없다.")
    return spec


def _steps_of(spec: Mapping[str, Any], job_key: str) -> list[dict[str, Any]]:
    job = (spec.get("jobs") or {}).get(job_key)
    if not isinstance(job, dict):
        return []
    return [s for s in (job.get("steps") or []) if isinstance(s, dict)]


def _runs(step: Mapping[str, Any], needle: str) -> bool:
    run = str(step.get("run") or "")
    return _HARNESS_CLI in run and needle in run.replace("\\\n", " ")


def _fail_open(step: Mapping[str, Any]) -> bool:
    return str(step.get("continue-on-error", "false")).lower() == "true"


def rule_index_wiring_violations(spec: Mapping[str, Any]) -> list[str]:
    """배선 계약 위반 목록(빈 리스트 = 정상) — 순수 함수라 합성 워크플로로 주입 가능."""
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        return ["ci.yml에 jobs가 없다 — 판정 불가(위장 통과 금지)."]

    violations: list[str] = []
    steps = _steps_of(spec, _EXPECTED_JOB)
    if not steps:
        return [
            f"`{_EXPECTED_JOB}` 잡이 없거나 스텝이 비었다 — 규칙 인덱스 린트가 "
            f"어디서 도는지 확인할 수 없다."
        ]

    for needle, label in ((_LINT_CMD, "린트"), (_RENDER_CHECK_CMD, "렌더 대조")):
        owning = [s for s in steps if _runs(s, needle)]
        if not owning:
            violations.append(
                f"`{_EXPECTED_JOB}` 잡에 `{_HARNESS_CLI} {needle}` 를 도는 스텝이 없다 — "
                f"{label}가 저장소에 존재해도 CI가 실행하지 않는다."
            )
            continue
        for step in owning:
            if _fail_open(step):
                violations.append(
                    f"`{_EXPECTED_JOB}` 잡의 {label} 스텝 '{step.get('name', '?')}' 에 "
                    f"continue-on-error: true — 깨져도 초록이라 배선이 있으나 마나다."
                )
    return violations


# ── 실제 저장소 상태 ─────────────────────────────────────────────────────────


def test_live_workflow_has_no_wiring_violations() -> None:
    assert rule_index_wiring_violations(_load_workflow()) == []


def test_lint_runs_in_a_job_that_installs_the_harness_runtime() -> None:
    """④ — 잡을 잘못 고르면 스텝은 존재하는데 파이썬·경로가 안 맞는다."""
    steps = _steps_of(_load_workflow(), _EXPECTED_JOB)
    assert any("setup-python" in str(s.get("uses", "")) for s in steps)
    assert any("pyyaml" in str(s.get("run") or "").lower() for s in steps)


def test_lint_precedes_nothing_it_depends_on() -> None:
    """린트는 저장소 파일만 읽는다 — 어느 스텝 뒤에 와도 되지만 잡 안에는 있어야 한다."""
    steps = _steps_of(_load_workflow(), _EXPECTED_JOB)
    assert [s for s in steps if _runs(s, _LINT_CMD)]


# ── 결함 주입 — 판정 함수가 *실제로* 실패 신호를 내는가 ─────────────────────


@pytest.fixture
def spec() -> dict[str, Any]:
    return copy.deepcopy(_load_workflow())


def _lint_step_index(spec: dict[str, Any]) -> int:
    steps = spec["jobs"][_EXPECTED_JOB]["steps"]
    return next(i for i, s in enumerate(steps) if _runs(s, _LINT_CMD))


def test_removing_the_lint_step_is_detected(spec: dict[str, Any]) -> None:
    del spec["jobs"][_EXPECTED_JOB]["steps"][_lint_step_index(spec)]
    violations = rule_index_wiring_violations(spec)
    assert any(_LINT_CMD in v for v in violations), violations


def test_dropping_the_render_check_is_detected(spec: dict[str, Any]) -> None:
    """린트만 남기면 문서가 대장과 어긋난 채 통과한다 — 조용한 표류."""
    i = _lint_step_index(spec)
    step = spec["jobs"][_EXPECTED_JOB]["steps"][i]
    step["run"] = str(step["run"]).replace(_RENDER_CHECK_CMD, "rules report")
    violations = rule_index_wiring_violations(spec)
    assert any(_RENDER_CHECK_CMD in v for v in violations), violations


def test_continue_on_error_is_detected(spec: dict[str, Any]) -> None:
    spec["jobs"][_EXPECTED_JOB]["steps"][_lint_step_index(spec)]["continue-on-error"] = True
    violations = rule_index_wiring_violations(spec)
    assert any("continue-on-error" in v for v in violations), violations


def test_moving_the_step_to_another_job_is_detected(spec: dict[str, Any]) -> None:
    """④ — 다른 잡으로 옮기면 하네스 런타임이 없는 곳에서 돌게 된다."""
    i = _lint_step_index(spec)
    step = spec["jobs"][_EXPECTED_JOB]["steps"].pop(i)
    spec["jobs"].setdefault("policy-guard", {"steps": []})["steps"].append(step)
    violations = rule_index_wiring_violations(spec)
    assert any(_LINT_CMD in v for v in violations), violations


def test_empty_workflow_fails_instead_of_passing_vacuously() -> None:
    assert rule_index_wiring_violations({"jobs": {}}) != []
    assert rule_index_wiring_violations({}) != []
    assert rule_index_wiring_violations({"jobs": {"other": {"steps": []}}}) != []
