"""[P3-14] Phase 3 지표 7종 CLI의 **위반 주입 반응 자가 점검** 배선 실재성 동결.

왜 이 테스트가 있는가
--------------------
`ops/phase3_metrics.py --self-check` 가 저장소에 존재하는 것과 CI가 실제로 그것을 실행하는 것은
다르다(CLAUDE.md "검증 장치를 만들고 배선 확인 없이 완료 선언 금지" — `test_qa_pipeline_wiring.py`
(ARCH-21)·`test_provenance_audit_wiring.py`(ARCH-20) 동형 선례). 이 테스트가 없으면 `ci.yml` 에서
이 스텝이 조용히 삭제돼도 아무 신호가 나지 않고, 7종 중 한 지표가 위반에 무반응이 되어도 CI 가
초록이다.

검증 계약
--------
① `backend` 잡에 `phase3_metrics` 모듈을 호출하는 `run` 스텝이 있다
② 그 스텝이 `-m whymath_backend.ops.phase3_metrics` 형태(패키지 모듈 실행)이고 `--self-check` 를 준다
③ 그 스텝에 `continue-on-error` 가 없다 — "돌아감 ≠ 막음"(ARCH-23)
④ 그 스텝에 `if:` 조건이 없다 — 조건부 스텝은 코퍼스·변경 경로에 따라 조용히 건너뛴다
⑤ ci.yml 어디에서든 이 모듈을 `--self-check` 없이 호출하는 줄이 없다 — 실 코퍼스 판정은 오늘의 실 상태가
   기준선 미달·측정 실패(exit 2)라 CI 에 걸면 상시 red 가 되어 게이트가 꺼진다. 그 결정(P3-14
   acceptance ⑥ 목표 미확정)을 기계로 동결한다. 걸고 싶어졌다면 Kiki 가 목표를 확정한 뒤 이 테스트를
   고치는 것이 올바른 순서다.
⑥ 파서가 위장하지 않는다 — 워크플로·잡을 못 찾으면 "위반 0 통과"가 아니라 **실패**
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_JOB_KEY = "backend"
_MODULE = "whymath_backend.ops.phase3_metrics"
_MODULE_INVOCATION = f"-m {_MODULE}"


def _load_ci() -> dict[str, Any]:
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 게이트 배선을 확인할 수 없다.")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("jobs"), dict):
        raise AssertionError("ci.yml 에 jobs 맵이 없다 — 파서가 위장하지 않도록 실패시킨다.")
    return dict(spec)


def _steps(job_key: str) -> list[dict[str, Any]]:
    jobs = _load_ci()["jobs"]
    if job_key not in jobs:
        raise AssertionError(
            f"ci.yml 에 `{job_key}` 잡이 없다 — 잡을 개명했다면 이 테스트도 고쳐라."
        )
    steps = (jobs[job_key] or {}).get("steps") or []
    out = [s for s in steps if isinstance(s, dict)]
    if not out:
        raise AssertionError(f"`{job_key}` 잡에 스텝이 하나도 없다.")
    return out


def _executable_lines(step: dict[str, Any]) -> list[str]:
    """스텝 `run` 의 실행 줄 — 빈 줄·주석 제외(설명 주석에 모듈명이 등장해도 오탐하지 않는다)."""
    return [
        ln.strip()
        for ln in str(step.get("run", "")).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _self_check_steps() -> list[dict[str, Any]]:
    return [
        s for s in _steps(_JOB_KEY) if any(_MODULE_INVOCATION in ln for ln in _executable_lines(s))
    ]


def test_phase3_metrics_self_check_step_exists_in_backend_job() -> None:
    assert _self_check_steps(), (
        f"`{_JOB_KEY}` 잡에 `{_MODULE_INVOCATION}` 호출 스텝이 없다 — Phase 3 지표 7종의 위반 주입 "
        "반응 자가 점검이 CI 에서 조용히 빠졌다(코드는 존재하나 실행되지 않는 상태)."
    )


def test_step_runs_the_self_check_in_module_form() -> None:
    steps = _self_check_steps()
    assert steps, "자가 점검 스텝을 찾을 수 없다(선행 테스트가 먼저 실패했을 것)."
    for step in steps:
        lines = [ln for ln in _executable_lines(step) if _MODULE_INVOCATION in ln]
        assert lines
        assert any("--self-check" in ln for ln in lines), (
            f"`{_MODULE_INVOCATION}` 스텝이 `--self-check` 를 주지 않는다 — 실 코퍼스 판정이 되어 "
            f"상시 red 가 된다: {step}"
        )


def test_step_has_no_continue_on_error() -> None:
    """무반응이 있어도 잡이 초록이면 게이트가 아니다(ARCH-23 선례)."""
    steps = _self_check_steps()
    assert steps
    for step in steps:
        assert "continue-on-error" not in step, f"자가 점검 스텝이 실패를 삼킨다: {step}"


def test_step_is_unconditional() -> None:
    steps = _self_check_steps()
    assert steps
    for step in steps:
        assert (
            "if" not in step
        ), f"자가 점검 스텝에 `if:` 조건이 있다 — 조건이 거짓인 실행에서는 도달하지 않는다: {step}"


def test_no_ci_step_runs_phase3_metrics_without_self_check() -> None:
    """실 코퍼스 판정(오늘 exit 2)을 CI 에 걸지 않는다는 결정의 동결."""
    offenders: list[str] = []
    for job_key, job in _load_ci()["jobs"].items():
        for step in (job or {}).get("steps") or []:
            if not isinstance(step, dict):
                continue
            for ln in _executable_lines(step):
                if "phase3_metrics" in ln and "--self-check" not in ln:
                    offenders.append(f"{job_key}: {ln}")
    assert not offenders, (
        "ci.yml 이 phase3_metrics 를 --self-check 없이 호출한다 — 오늘의 실 상태(기준선 미달·측정 "
        f"실패)에서는 상시 red 다: {offenders}"
    )


def test_missing_job_is_a_failure_not_a_pass() -> None:
    """파서가 잡을 못 찾았을 때 '호출 0건 = 위반 없음'으로 접히지 않는다."""
    try:
        _steps("no-such-job-exists")
    except AssertionError:
        return
    raise AssertionError("없는 잡 이름이 실패하지 않았다 — 이 테스트의 파서가 위장한다")
