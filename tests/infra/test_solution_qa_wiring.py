"""[P3-07] Solution QA 게이트의 **CI 배선 실재성** 동결.

왜 이 테스트가 있는가
--------------------
`harness/solution_qa.py` 가 저장소에 존재하는 것과 CI 가 실제로 그것을 실행하는 것은 다르다
(CLAUDE.md "검증 장치를 만들고 배선 확인 없이 완료 선언 금지" — `test_phase3_metrics_wiring.py` 동형).
이 테스트가 없으면 `ci.yml` 에서 스텝이 조용히 삭제되거나 `continue-on-error`·`if:` 가 붙어도 아무
신호가 없고, 문항 하나의 정답이 어긋나도 CI 가 초록이다.

검증 계약
--------
① `backend` 잡에 `whymath_backend.harness.solution_qa` 를 모듈 형태(`-m`)로 호출하는 `run` 스텝이 있다
② 그 스텝은 인자 없이(= 대표 과정 전수 모드) 돈다 — JSONL 경로나 출력 옵션을 붙이면 모집단이 바뀌어
   게이트의 뜻이 달라진다
③ `continue-on-error` 가 없다 — "돌아감 ≠ 막음"(ARCH-23)
④ `if:` 조건이 없다 — 조건부 스텝은 변경 경로에 따라 조용히 건너뛴다
⑤ 파서가 위장하지 않는다 — 워크플로·잡을 못 찾으면 통과가 아니라 실패
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_JOB_KEY = "backend"
_MODULE = "whymath_backend.harness.solution_qa"
_INVOCATION = f"-m {_MODULE}"


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
    steps = [s for s in ((jobs[job_key] or {}).get("steps") or []) if isinstance(s, dict)]
    if not steps:
        raise AssertionError(f"`{job_key}` 잡에 스텝이 하나도 없다.")
    return steps


def _executable_lines(step: dict[str, Any]) -> list[str]:
    """스텝 `run` 의 실행 줄 — 빈 줄·주석 제외(설명 주석에 모듈명이 나와도 오탐하지 않는다)."""
    return [
        ln.strip()
        for ln in str(step.get("run", "")).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _gate_steps() -> list[dict[str, Any]]:
    return [s for s in _steps(_JOB_KEY) if any(_INVOCATION in ln for ln in _executable_lines(s))]


def test_solution_qa_gate_step_exists_in_backend_job() -> None:
    assert _gate_steps(), (
        f"`{_JOB_KEY}` 잡에 `{_INVOCATION}` 호출 스텝이 없다 — Solution QA 가 CI 에서 조용히 빠졌다"
        "(코드는 존재하나 실행되지 않는 상태)."
    )


def test_gate_runs_in_representative_scope_mode_without_arguments() -> None:
    for step in _gate_steps():
        lines = [ln for ln in _executable_lines(step) if _INVOCATION in ln]
        assert lines
        for ln in lines:
            tail = ln.split(_MODULE, 1)[1].strip()
            assert tail == "", (
                f"게이트 스텝이 `{tail}` 인자를 준다 — 모집단(대표 과정 전수)이 바뀌어 게이트의 뜻이 "
                f"달라진다: {ln}"
            )


def test_gate_step_has_no_continue_on_error() -> None:
    steps = _gate_steps()
    assert steps
    for step in steps:
        assert "continue-on-error" not in step, f"게이트가 실패를 삼킨다: {step}"


def test_gate_step_is_unconditional() -> None:
    steps = _gate_steps()
    assert steps
    for step in steps:
        assert (
            "if" not in step
        ), f"게이트에 `if:` 조건이 있다 — 거짓인 실행에서는 도달하지 않는다: {step}"
