"""[OPS-56] 주간 KPI 집계 cron — 배선 실재성 동결(`tests/infra/test_anchor_e2e_nightly_wiring.py`
동형 패턴).

왜 이 테스트가 있는가
--------------------
`ops/weekly_metrics_report.py`가 저장소에 존재하는 것과, 그것이 **실제로 매주 발화하는
워크플로에 물려 있는가**는 다른 질문이다(OPS-10 `test_test_suite_wiring.py` 선례 —
"저장소에 존재함"과 "돌아감"은 다르다). acceptance①의 "월 07:00 KST cron(UTC 변환 명시)"이
워크플로 YAML에 실제로 있는지, acceptance②의 "측정 실패가 '0'으로 위장되지 않는" 최소 경보
스텝이 fail-open으로 무력화되지 않았는지를 기계로 고정한다.

검증 계약 (각 항목은 변별력이 확인된 것만)
----------------------------------------
① `weekly-metrics.yml`이 디스크에 실재한다.
② `on.schedule`에 정확히 `"0 22 * * 0"`(= KST 월 07:00)이 있다 — 값 자체를 고정한다
   (존재만 보면 "아무 요일 아무 시각"도 통과해 acceptance①의 "월 07:00" 약속을 안 지킨다).
③ 어떤 잡의 어떤 스텝이 `python -m whymath_backend.ops.weekly_metrics_report`를 돈다
   (실행기 단독 호출 금지 — CLAUDE.md와 동형 근거: 다중 환경에서 바레 실행기는 다른
   인터프리터에 결합될 수 있다).
④ 그 스텝에 `continue-on-error: true`가 없다(fail-open이면 집계가 깨져도 잡이 초록이다).
⑤ "최소 경보" 스텝(DB 실패 grep + `exit 1`)이 실재하고, 그 스텝도 fail-open이 아니다 —
   acceptance②(측정 실패≠0 위장)가 잡 상태에도 반영되는지의 집행 지점.
⑥ 파서가 위장하지 않는다 — 못 읽거나 jobs가 비면 실패.
⑦ 판정 함수의 변별력을 결함 주입으로 매번 재확인한다(양성 대조 포함).

의도적으로 검증하지 않는 것 (정직한 공백)
--------------------------------------
- **집계 로직 자체의 정확성**은 이 파일의 관심이 아니다 — `test_weekly_metrics_report.py`(순수
  로직)·`test_weekly_metrics_report_integration.py`(실 PG)가 담당한다. 여기서 보는 것은
  "매주 그 로직이 실제로 발화하는가"뿐이다.
- **PR 생성·auto-merge 스텝의 성공 여부**는 실측하지 않는다(GitHub API 실호출 필요 —
  하네스가 오프라인·CI 파싱만으로 fail-open이 되므로 이 축은 의도적 미채택. 워크플로 파일
  안에 그 스텝이 문자열로 존재하는지 정도만 다른 스텝들과 함께 파싱 성공을 확인한다).
- **cron 발화 지연·GitHub 스케줄 큐 신뢰성**은 GitHub 인프라 영역 — 우리 코드가 볼 수 없다.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "weekly-metrics.yml"

_EXPECTED_CRON = "0 22 * * 0"  # 일 22:00 UTC = 월 07:00 KST(UTC+9)
_REPORT_MODULE = "whymath_backend.ops.weekly_metrics_report"
_ALERT_MARKER = "DB 연결/조회 실패"


def _load_workflow() -> dict[str, Any]:
    """weekly-metrics.yml 파싱 — 못 읽거나 jobs가 비면 '통과'가 아니라 AssertionError(⑥)."""
    if not _WORKFLOW_PATH.is_file():
        raise AssertionError(
            f"{_WORKFLOW_PATH} 이(가) 없다 — 주간 cron 배선을 확인할 수 없다(위장 통과 금지)."
        )
    spec: Any = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("weekly-metrics.yml에 jobs가 없다 — 파싱이 위장 통과할 수 없다.")
    return spec


def _all_steps(spec: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict):
        return out
    for job_key, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                out.append((job_key, step))
    return out


def _invokes_module_via_python(script: str, *, module: str) -> bool:
    """`python -m <module>` 형태로 도는가 — bare 실행기·직접 스크립트 경로 호출은 배제한다."""
    tokens = script.replace("\\\n", " ").split()
    for i, token in enumerate(tokens[:-2]):
        name = Path(token).name
        if name.startswith("python") and tokens[i + 1] == "-m" and tokens[i + 2] == module:
            return True
    return False


def weekly_metrics_wiring_violations(spec: Mapping[str, Any]) -> list[str]:
    """배선 계약 위반 목록(빈 리스트 = 배선 정상) — 순수 함수라 합성 워크플로로 봉인 가능."""
    violations: list[str] = []
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        return ["weekly-metrics.yml에 jobs가 없다 — 판정 불가(위장 통과 금지)."]

    # ② cron 값 자체를 고정 — 존재만으로는 "아무 때나"도 통과한다.
    on_spec = spec.get("on") or spec.get(True)  # YAML 1.1에서 bare `on:`은 True로 파싱된다
    schedule = (on_spec or {}).get("schedule") if isinstance(on_spec, dict) else None
    crons = [entry.get("cron") for entry in schedule or [] if isinstance(entry, dict)]
    if _EXPECTED_CRON not in crons:
        violations.append(
            f"`on.schedule`에 '{_EXPECTED_CRON}'(월 07:00 KST)이 없다 — 발견된 cron: {crons!r}."
        )

    steps = _all_steps(spec)

    # ③④ 집계 모듈을 실행하는 스텝 — python -m 형태·fail-open 아님.
    report_steps = [
        (job_key, step)
        for job_key, step in steps
        if step.get("run") and _invokes_module_via_python(str(step["run"]), module=_REPORT_MODULE)
    ]
    if not report_steps:
        violations.append(
            f"`python -m {_REPORT_MODULE}`를 도는 스텝이 없다 — 집계 로직이 존재해도 아무도 "
            "매주 실행하지 않는 상태(acceptance① 미배선)."
        )
    for job_key, step in report_steps:
        if str(step.get("continue-on-error", "false")).lower() == "true":
            violations.append(
                f"`{job_key}` 잡의 집계 스텝에 continue-on-error: true — 집계가 깨져도 초록."
            )

    # ⑤ 최소 경보 스텝 — DB 실패 문자열을 검사하고 exit 1로 잡을 red로 만드는가.
    alert_steps = [
        (job_key, step)
        for job_key, step in steps
        if step.get("run") and _ALERT_MARKER in str(step["run"])
    ]
    if not alert_steps:
        violations.append(
            f"'{_ALERT_MARKER}' 문자열을 검사하는 최소 경보 스텝이 없다 — DB 구조적 실패가 "
            "그냥 '0'으로 조용히 append될 위험(acceptance② 미배선)."
        )
    for job_key, step in alert_steps:
        if str(step.get("continue-on-error", "false")).lower() == "true":
            violations.append(
                f"`{job_key}` 잡의 최소 경보 스텝에 continue-on-error: true — 경보가 절대 "
                "잡을 red로 만들 수 없다(fail-open 위장)."
            )
        script = str(step["run"])
        if "exit 1" not in script:
            violations.append(
                f"`{job_key}` 잡의 최소 경보 스텝에 'exit 1'이 없다 — 문자열만 echo하고 잡은 "
                "계속 초록이면 최소 경보가 아니라 로그 한 줄이다."
            )

    return violations


# ══════════════════════════════════════════════════════════════════════════
# 실 워크플로 판정
# ══════════════════════════════════════════════════════════════════════════
def test_weekly_metrics_workflow_file_exists() -> None:
    """① 배선 대상 파일이 실재한다."""
    assert _WORKFLOW_PATH.is_file(), (
        f"{_WORKFLOW_PATH} 이(가) 없다 — OPS-56 acceptance①(월 07:00 KST cron)이 배선되지 "
        "않았다."
    )


def test_weekly_metrics_cron_is_wired_correctly() -> None:
    """②③④⑤ 실 workflow가 정확한 cron·집계 스텝·경보 스텝을 fail-closed로 갖는다."""
    violations = weekly_metrics_wiring_violations(_load_workflow())
    assert violations == [], "주간 cron 배선 계약 위반:\n" + "\n".join(f"- {v}" for v in violations)


def test_parser_refuses_to_pass_on_broken_workflow() -> None:
    """⑥ 파서가 위장하지 않는다 — jobs 없는 워크플로는 '위반 0'이 아니라 위반으로 잡힌다."""
    assert weekly_metrics_wiring_violations({"jobs": {}}) != []
    assert weekly_metrics_wiring_violations({}) != []


# ══════════════════════════════════════════════════════════════════════════
# ⑦ 변별력 봉인 — 결함 주입이 실제로 검출되는지 매번 재확인
# ══════════════════════════════════════════════════════════════════════════
def _synthetic_workflow(
    *,
    cron: str | None = _EXPECTED_CRON,
    report_run: str = f"python -m {_REPORT_MODULE} --metrics-path ../../metrics/weekly.json",
    report_continue_on_error: bool = False,
    alert_run: str = f'if grep -q "{_ALERT_MARKER}" out.json; then exit 1; fi',
    alert_continue_on_error: bool = False,
    include_alert_step: bool = True,
) -> dict[str, Any]:
    """정상 배선 1건짜리 합성 워크플로 — 인자로 축 하나씩 깨뜨려 검출을 확인한다."""
    report_step: dict[str, Any] = {"name": "집계", "run": report_run}
    if report_continue_on_error:
        report_step["continue-on-error"] = True
    steps = [report_step]
    if include_alert_step:
        alert_step: dict[str, Any] = {"name": "경보", "run": alert_run}
        if alert_continue_on_error:
            alert_step["continue-on-error"] = True
        steps.append(alert_step)
    spec: dict[str, Any] = {"on": {"workflow_dispatch": None}, "jobs": {"report": {"steps": steps}}}
    if cron is not None:
        spec["on"]["schedule"] = [{"cron": cron}]
    return spec


def test_positive_control_synthetic_wiring_passes() -> None:
    """양성 대조 — 정상 합성 배선은 위반 0(무차별 실패가 아님을 보인다)."""
    assert weekly_metrics_wiring_violations(_synthetic_workflow()) == []


def test_detects_missing_schedule_trigger() -> None:
    """결함 주입 ⓐ — cron 트리거 자체가 사라지면 영원히 발화하지 않는다."""
    assert weekly_metrics_wiring_violations(_synthetic_workflow(cron=None)) != []


def test_detects_wrong_cron_value() -> None:
    """결함 주입 ⓑ — cron이 있어도 값이 다르면(예: 매일 자정) 약속한 시각이 아니다."""
    assert weekly_metrics_wiring_violations(_synthetic_workflow(cron="0 0 * * *")) != []


def test_detects_missing_report_step() -> None:
    """결함 주입 ⓒ — 집계 모듈을 안 부르면 스케줄만 있고 실행이 없다."""
    broken = _synthetic_workflow(report_run="echo 'nothing to do'")
    assert weekly_metrics_wiring_violations(broken) != []


def test_detects_bare_module_launcher() -> None:
    """결함 주입 ⓓ — `-m` 없이 스크립트 경로를 직접 부르면 인터프리터 결합이 결정 불가."""
    broken = _synthetic_workflow(report_run=f"python {_REPORT_MODULE.replace('.', '/')}.py")
    assert weekly_metrics_wiring_violations(broken) != []


def test_detects_report_step_fail_open() -> None:
    """결함 주입 ⓔ — 집계 스텝의 continue-on-error: true는 실패를 초록으로 위장한다."""
    assert (
        weekly_metrics_wiring_violations(_synthetic_workflow(report_continue_on_error=True)) != []
    )


def test_detects_missing_alert_step() -> None:
    """결함 주입 ⓕ — 최소 경보 스텝 자체가 없으면 DB 구조적 실패가 조용히 묻힌다."""
    assert weekly_metrics_wiring_violations(_synthetic_workflow(include_alert_step=False)) != []


def test_detects_alert_step_fail_open() -> None:
    """결함 주입 ⓖ — 경보 스텝의 continue-on-error: true는 경보를 무력화한다."""
    assert weekly_metrics_wiring_violations(_synthetic_workflow(alert_continue_on_error=True)) != []


def test_detects_alert_step_without_exit() -> None:
    """결함 주입 ⓗ — exit 1이 빠지면 grep이 매치해도 잡은 계속 초록이다(echo만 하는 위장)."""
    broken = _synthetic_workflow(alert_run=f'grep "{_ALERT_MARKER}" out.json || true')
    assert weekly_metrics_wiring_violations(broken) != []
