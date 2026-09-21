"""HARN-118 ③ — 하네스 지표 3종의 **집행 지점** 동결.

정본화 ≠ 집행
-------------
`weekly_metrics_report.py`가 `--incidents-summary`를 읽을 수 있다는 것과, 매주
누군가 실제로 그 파일을 만들어 건네준다는 것은 다른 질문이다. 이 저장소는
"만들었는데 어느 잡도 실행하지 않던" 상태를 반복해 겪었다(OPS-03 `tests/infra`
199건 미실행 · OPS-08 required check 미강제 · OPS-11 lint 잡 부재). 그래서 계약을
만든 태스크의 acceptance는 정본화와 집행 지점을 별항으로 나누고, 이 파일이 후자를
기계로 고정한다.

검증 계약 (각 항목은 결함 주입으로 변별력을 확인한 것만)
-------------------------------------------------------
① 하네스 집계 스텝이 실재한다 — `scripts/harness/backlog.py incident report --json`.
② 그 스텝이 산출 파일로 리다이렉트하고, 집계 스텝이 **같은 경로**를 `--incidents-summary`로
   받는다(두 스텝이 서로 다른 파일을 보면 배선은 조용히 끊긴 채 초록이다).
③ 하네스 스텝이 집계 스텝보다 **앞**에 있다(뒤에 있으면 매주 직전 회차 파일을 읽거나
   아무것도 못 읽는다 — CLAUDE.md "지금 보는 것이 이번 실행 것인가").
④ 두 스텝 다 `continue-on-error: true`가 아니다(fail-open이면 깨져도 잡이 초록).
⑤ 파서가 위장하지 않는다 — 못 읽거나 jobs가 비면 통과가 아니라 실패.

의도적으로 검증하지 않는 것 (정직한 공백)
--------------------------------------
- **집계 숫자의 정확성**은 `tests/harness/test_incidents.py`(시드 676건 ↔ 보고서 §2
  재계산 일치)가 담당한다. 여기서 보는 것은 "매주 그 명령이 실제로 도는가"뿐이다.
- **GitHub Actions가 실제로 발화했는가**는 우리 코드가 볼 수 없다(cron 신뢰성은
  기존 `test_weekly_metrics_cron_wiring.py`가 cron 값 고정까지만 본다).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "weekly-metrics.yml"

_HARNESS_CLI = "scripts/harness/backlog.py"
_HARNESS_ARGS = ("incident", "report", "--json")
_SUMMARY_FLAG = "--incidents-summary"
_REPORT_MODULE = "whymath_backend.ops.weekly_metrics_report"


def _load_workflow() -> dict[str, Any]:
    if not _WORKFLOW_PATH.is_file():
        raise AssertionError(f"{_WORKFLOW_PATH} 이(가) 없다 — 판정 불가(위장 통과 금지).")
    spec: Any = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("weekly-metrics.yml에 jobs가 없다.")
    return spec


def _ordered_steps(spec: Mapping[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    """(잡 이름, 잡 안에서의 순서, 스텝). 순서를 들고 다녀야 ③을 볼 수 있다."""
    out: list[tuple[str, int, dict[str, Any]]] = []
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict):
        return out
    for job_key, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or []):
            if isinstance(step, dict):
                out.append((job_key, index, step))
    return out


def _bare(token: str) -> str:
    """셸 토큰에서 인용부호·배열 닫는 괄호를 벗긴다.

    워크플로에서 플래그 값은 bash 배열 안에 있어(`ARGS+=(... "$X/f.json")`) 토큰이
    `"$X/f.json")` 로 잡힌다. 따옴표만 벗기면 산출 경로와 영원히 안 맞고, 그러면 이
    판정기는 **정상 상태에서도 위반을 보고하는** 상시 red가 된다 — 상시 실패하는
    판정기는 사람이 판정기를 끄게 만든다(CLAUDE.md fail-open 항목의 역방향).
    """
    return token.strip().strip("\"'").rstrip(")").strip("\"'")


def _redirect_target(script: str) -> str | None:
    """`... > <경로>` 의 대상 — 줄바꿈 이음(`\\`)을 편 뒤 `>` 다음 토큰."""
    tokens = script.replace("\\\n", " ").split()
    for i, token in enumerate(tokens[:-1]):
        if token == ">":
            return _bare(tokens[i + 1])
    return None


def _flag_value(script: str, flag: str) -> str | None:
    tokens = script.replace("\\\n", " ").split()
    for i, token in enumerate(tokens[:-1]):
        if token == flag:
            return _bare(tokens[i + 1])
    return None


def _runs_harness_report(script: str) -> bool:
    flat = script.replace("\\\n", " ")
    return _HARNESS_CLI in flat and all(arg in flat.split() for arg in _HARNESS_ARGS)


def _fail_open(step: Mapping[str, Any]) -> bool:
    return str(step.get("continue-on-error", "false")).lower() == "true"


def incident_metrics_wiring_violations(spec: Mapping[str, Any]) -> list[str]:
    """배선 계약 위반 목록(빈 리스트 = 정상) — 순수 함수라 합성 워크플로로 주입 가능."""
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        return ["weekly-metrics.yml에 jobs가 없다 — 판정 불가(위장 통과 금지)."]

    violations: list[str] = []
    steps = _ordered_steps(spec)

    harness_steps = [
        (job, idx, step)
        for job, idx, step in steps
        if step.get("run") and _runs_harness_report(str(step["run"]))
    ]
    consumer_steps = [
        (job, idx, step)
        for job, idx, step in steps
        if step.get("run") and _SUMMARY_FLAG in str(step["run"])
    ]

    # ① 하네스 집계 스텝 실재
    if not harness_steps:
        violations.append(
            f"`{_HARNESS_CLI} {' '.join(_HARNESS_ARGS)}` 를 도는 스텝이 없다 — "
            "하네스 지표 3종의 입력을 아무도 만들지 않는다(집행 지점 부재)."
        )
    # ①-b 소비 스텝 실재
    if not consumer_steps:
        violations.append(
            f"`{_SUMMARY_FLAG}` 를 넘기는 스텝이 없다 — 하네스 집계가 돌아도 주간 원장에 "
            "실리지 않는다(정본화만 있고 집행이 없다)."
        )

    # ② 산출 경로 ↔ 소비 경로 일치
    produced = {_redirect_target(str(s["run"])) for _, _, s in harness_steps}
    consumed = {_flag_value(str(s["run"]), _SUMMARY_FLAG) for _, _, s in consumer_steps}
    produced.discard(None)
    consumed.discard(None)
    if harness_steps and not produced:
        violations.append("하네스 집계 스텝이 산출 파일로 리다이렉트하지 않는다 — 결과가 휘발된다.")
    if produced and consumed and not (produced & consumed):
        violations.append(
            f"하네스 산출 경로 {sorted(produced)} 와 소비 경로 {sorted(consumed)} 가 "
            "겹치지 않는다 — 배선이 끊긴 채 초록이 된다."
        )

    # ③ 순서 — 같은 잡 안에서 생산이 소비보다 앞
    for cjob, cidx, _ in consumer_steps:
        same_job = [idx for hjob, idx, _ in harness_steps if hjob == cjob]
        if not same_job:
            violations.append(
                f"`{cjob}` 잡이 {_SUMMARY_FLAG} 를 쓰는데 같은 잡에 하네스 집계 스텝이 없다 — "
                "잡 경계를 넘은 파일은 러너에 남지 않는다."
            )
        elif min(same_job) >= cidx:
            violations.append(
                f"`{cjob}` 잡에서 하네스 집계 스텝이 소비 스텝보다 뒤에 있다 "
                f"(생산 {min(same_job)} ≥ 소비 {cidx}) — 이번 실행 것을 읽을 수 없다."
            )

    # ④ fail-open 금지
    for job, _, step in harness_steps + consumer_steps:
        if _fail_open(step):
            violations.append(
                f"`{job}` 잡의 스텝 '{step.get('name', '?')}' 에 continue-on-error: true — "
                "깨져도 초록이라 배선이 있으나 마나다."
            )
    return violations


# ── 실제 저장소 상태 ─────────────────────────────────────────────────────────


def test_live_workflow_has_no_wiring_violations() -> None:
    assert incident_metrics_wiring_violations(_load_workflow()) == []


def test_report_step_is_the_one_consuming_the_summary() -> None:
    """소비자가 *주간 집계 모듈* 자신인지 — 엉뚱한 스텝이 플래그만 들고 있어도 통과하면 안 된다."""
    consumers = [
        step
        for _, _, step in _ordered_steps(_load_workflow())
        if step.get("run") and _SUMMARY_FLAG in str(step["run"])
    ]
    assert consumers, "소비 스텝이 없다"
    assert all(_REPORT_MODULE in str(step["run"]) for step in consumers)


# ── 결함 주입 — 판정 함수가 *실제로* 실패 신호를 내는가 ─────────────────────


@pytest.fixture
def spec() -> dict[str, Any]:
    return copy.deepcopy(_load_workflow())


def _the_job(spec: dict[str, Any]) -> dict[str, Any]:
    return next(job for job in spec["jobs"].values() if isinstance(job, dict) and job.get("steps"))


def _index_of(job: dict[str, Any], needle: str) -> int:
    return next(i for i, s in enumerate(job["steps"]) if needle in str(s.get("run", "")))


def test_removing_the_harness_step_is_detected(spec: dict[str, Any]) -> None:
    job = _the_job(spec)
    del job["steps"][_index_of(job, _HARNESS_CLI)]
    violations = incident_metrics_wiring_violations(spec)
    assert any(_HARNESS_CLI in v for v in violations), violations


def test_removing_the_summary_flag_is_detected(spec: dict[str, Any]) -> None:
    job = _the_job(spec)
    i = _index_of(job, _SUMMARY_FLAG)
    job["steps"][i]["run"] = str(job["steps"][i]["run"]).replace(_SUMMARY_FLAG, "--unused-flag")
    violations = incident_metrics_wiring_violations(spec)
    assert any(_SUMMARY_FLAG in v for v in violations), violations


def test_mismatched_paths_are_detected(spec: dict[str, Any]) -> None:
    """두 스텝이 서로 다른 파일을 보는 경우 — 가장 조용한 형태의 배선 단절."""
    job = _the_job(spec)
    i = _index_of(job, _SUMMARY_FLAG)
    job["steps"][i]["run"] = str(job["steps"][i]["run"]).replace(
        f'{_SUMMARY_FLAG} "$RUNNER_TEMP/incidents_summary.json"',
        f'{_SUMMARY_FLAG} "$RUNNER_TEMP/somewhere_else.json"',
    )
    violations = incident_metrics_wiring_violations(spec)
    assert any("겹치지 않는다" in v for v in violations), violations


def test_swapped_order_is_detected(spec: dict[str, Any]) -> None:
    job = _the_job(spec)
    hi, ci = _index_of(job, _HARNESS_CLI), _index_of(job, _SUMMARY_FLAG)
    job["steps"][hi], job["steps"][ci] = job["steps"][ci], job["steps"][hi]
    violations = incident_metrics_wiring_violations(spec)
    assert any("뒤에 있다" in v for v in violations), violations


def test_lost_redirect_is_detected(spec: dict[str, Any]) -> None:
    job = _the_job(spec)
    i = _index_of(job, _HARNESS_CLI)
    job["steps"][i]["run"] = str(job["steps"][i]["run"]).replace(
        '> "$RUNNER_TEMP/incidents_summary.json"', ""
    )
    violations = incident_metrics_wiring_violations(spec)
    assert any("휘발" in v or "겹치지 않는다" in v for v in violations), violations


@pytest.mark.parametrize("needle", [_HARNESS_CLI, _SUMMARY_FLAG])
def test_continue_on_error_is_detected(spec: dict[str, Any], needle: str) -> None:
    job = _the_job(spec)
    job["steps"][_index_of(job, needle)]["continue-on-error"] = True
    violations = incident_metrics_wiring_violations(spec)
    assert any("continue-on-error" in v for v in violations), violations


def test_empty_workflow_fails_instead_of_passing_vacuously(spec: dict[str, Any]) -> None:
    """스캔 0건은 실패다 — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다."""
    assert incident_metrics_wiring_violations({"jobs": {}}) != []
    assert incident_metrics_wiring_violations({}) != []
