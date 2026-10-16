"""오답 → 교정 전 구간 계측기(P3-06)가 CI backend 잡에서 **실제로 실패를 만들 수 있게** 배선됐는가.

"저장소에 존재함"과 "CI에서 돌아 red를 낼 수 있음"은 다르다(CLAUDE.md 검증 장치 배선 규칙). 이 파일은
`ci.yml`을 파싱해 정적으로 동결한다:

  ① backend 잡에 계측기 모듈을 `python -m`으로 부르는 스텝이 있다.
  ② 그 스텝은 실패를 삼키지 않는다 — `continue-on-error`·`|| true`·`; true`가 없다.
  ③ `--require-all`을 달지 않는다(좌석 없는 5개가 처분 대기인 동안 CI가 영구 red가 되므로) — 이 결정이
     바뀌면(게이트 처분이 끝나면) 이 단언을 반대로 뒤집어야 한다는 신호다.
  ④ 대상 모듈 파일이 실제로 존재한다.
  ⑤ 파서가 위장하지 않는다 — 잡·스텝을 하나도 못 찾으면 0건 통과가 아니라 예외다.

합성 YAML로 각 단언이 **실제로 RED를 내는지**(변별력)도 확인한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_CI = _REPO / ".github" / "workflows" / "ci.yml"
_MODULE = "whymath_backend.harness.wrong_answer_remediation_report"
_MODULE_FILE = (
    _REPO / "src" / "backend" / "whymath_backend" / "harness" / "wrong_answer_remediation_report.py"
)


def _load(text: str) -> dict[str, Any]:
    doc = yaml.safe_load(text)
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        raise AssertionError("ci.yml에서 잡을 하나도 못 읽었다 — 파서가 위장하면 안 된다")
    return jobs  # type: ignore[no-any-return]


def _gate_steps(jobs: dict[str, Any], job: str = "backend") -> Iterator[dict[str, Any]]:
    steps = (jobs.get(job) or {}).get("steps")
    if not isinstance(steps, list) or not steps:
        raise AssertionError(f"{job} 잡에서 스텝을 하나도 못 읽었다")
    for step in steps:
        if isinstance(step, dict) and _MODULE in str(step.get("run", "")):
            yield step


def _violations(jobs: dict[str, Any]) -> list[str]:
    found = list(_gate_steps(jobs))
    if not found:
        return ["① backend 잡에 계측기 스텝이 없다"]
    problems: list[str] = []
    for step in found:
        run = str(step.get("run", ""))
        if step.get("continue-on-error"):
            problems.append("② continue-on-error — 실패를 삼킨다")
        if "|| true" in run or "; true" in run or "||true" in run:
            problems.append("② `|| true` — 종료 코드를 가린다")
        if "--require-all" in run:
            problems.append("③ --require-all — 처분 대기 갭 때문에 CI가 영구 red가 된다")
        if f"python -m {_MODULE}" not in run:
            problems.append("① `python -m`으로 부르지 않는다")
    return problems


def _synthetic(run: str, **step_extra: Any) -> dict[str, Any]:
    step = {"name": "게이트", "run": run, **step_extra}
    return {"backend": {"steps": [step]}}


class TestRealWorkflow:
    def test_backend_job_runs_the_gate_without_swallowing_failure(self) -> None:
        jobs = _load(_CI.read_text(encoding="utf-8"))
        assert _violations(jobs) == []

    def test_module_file_exists(self) -> None:
        assert _MODULE_FILE.is_file()


class TestWiringChecksActuallyDiscriminate:
    """각 단언이 위반 상태를 주입했을 때 실제로 RED를 낸다."""

    def test_missing_step_is_red(self) -> None:
        assert _violations({"backend": {"steps": [{"name": "x", "run": "echo hi"}]}})

    @pytest.mark.parametrize(
        "run",
        [
            f"python -m {_MODULE} --no-sweep || true",
            f"python -m {_MODULE} --no-sweep; true",
            f"python -m {_MODULE} --require-all",
            f"{_MODULE} --no-sweep",
        ],
    )
    def test_bad_run_lines_are_red(self, run: str) -> None:
        assert _violations(_synthetic(run))

    def test_continue_on_error_is_red(self) -> None:
        assert _violations(_synthetic(f"python -m {_MODULE}", **{"continue-on-error": True}))

    def test_good_step_is_green(self) -> None:
        assert _violations(_synthetic(f"python -m {_MODULE} --no-sweep")) == []

    def test_parser_does_not_masquerade_as_pass(self) -> None:
        with pytest.raises(AssertionError):
            _load("name: empty\n")
        with pytest.raises(AssertionError):
            list(_gate_steps({"backend": {"steps": []}}))
