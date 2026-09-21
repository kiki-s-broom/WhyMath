#!/usr/bin/env python3
"""CI 미러 — ci.yml의 잡 스텝을 로컬에서 그대로 실행한다 (HARN-119).

왜 필요한가:
  검사 판정 무효화 계열이 네 번 뚫렸다(2026-08-09·09-10·09-17·09-19). 공통 원인은
  **로컬 검증의 범위를 사람이 매번 손으로 고른다**는 것이다. `/drive` 런북은 "pytest·ruff
  green"만 요구하는데 backend 잡은 26스텝이다. 사람이 고르는 한 다음 회차에도 하나를
  빠뜨린다 — 규칙이 아니라 도구가 필요한 자리다.

  HARN-109(ci_job_coverage)가 "무엇을 봐야 하는가"를 계산한다면, 이 도구는 그것을
  **실제로 돌리고** 스텝별 exit code와 *뒤따라 건너뛴 스텝 수*를 센다. 뒤 스텝이 skipped가
  되면 화면에서 red가 아니므로, 실패 1건이 검증 표면 20건을 통째로 삼킨 것을 사람이
  놓친다(2026-09-10 PR #1075의 실제 형태).

설계 원칙 (측정 도구 실패 경로 — CLAUDE.md 2026-08-22):
  · 스텝마다 즉시 flush — 중간에 멈춰도 거기까지의 증거가 남는다
  · 실패 *원인*을 남긴다 — exit code만이 아니라 stderr 꼬리를 함께 기록
  · 모든 서브프로세스에 타임아웃 — 무한 대기로 측정 회차를 태우지 않는다
  · 지금 보는 것이 이번 실행인가 — 결과 JSON에 기준 커밋 해시를 박는다

범위:
  `uses:` 액션 스텝(체크아웃·setup-python 등)은 로컬에서 실행하지 않는다. "환경 전제"로
  표기하며 통과로 계상하지 않는다 — 실행하지 않은 것을 실행했다고 세는 것이 빠뜨리는 것보다
  나쁘다. 서비스 컨테이너·docker 빌드가 필요한 잡도 같은 이유로 실행 대상에서 제외된다
  (HARN-109가 '재현 불가'로 판정한 잡).

exit code: 0 전 스텝 통과 · 1 실패 스텝 존재 · 2 사용 오류(잡 이름 오타·파싱 0건)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_job_coverage as coverage  # noqa: E402  (경로 삽입 후 임포트)

DEFAULT_WORKFLOW = Path(".github/workflows/ci.yml")

#: 결과 JSON 기본 경로. .gitignore의 `.claude/cache/` 아래라 저장소를 더럽히지 않는다.
DEFAULT_RESULT_PATH = Path(".claude/cache/ci_mirror.json")

#: 스텝 하나의 기본 상한(초). CI 잡 자체가 35분 상한이므로 그보다 넉넉히 두되 무한은 아니다.
DEFAULT_STEP_TIMEOUT = 2400

PASSED = "passed"
FAILED = "failed"
SKIPPED_AFTER_FAILURE = "skipped_after_failure"
NOT_RUNNABLE = "not_runnable"


class MirrorUsageError(RuntimeError):
    """잡 이름 오타·스텝 파싱 0건 등 사용 오류 — 통과가 아니라 exit 2."""


@dataclass
class StepResult:
    name: str
    status: str
    exit_code: int | None = None
    duration_s: float = 0.0
    reason: str = ""
    stderr_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 2),
            "reason": self.reason,
            "stderr_tail": self.stderr_tail[-800:],
        }


@dataclass
class JobResult:
    name: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == FAILED]

    @property
    def skipped_after_failure(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == SKIPPED_AFTER_FAILURE]

    @property
    def not_runnable(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == NOT_RUNNABLE]

    @property
    def exit_code(self) -> int:
        return 1 if self.failed_steps else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "exit": self.exit_code,
            "step_count": len(self.steps),
            "passed": len([s for s in self.steps if s.status == PASSED]),
            "failed": len(self.failed_steps),
            "skipped_after_failure": len(self.skipped_after_failure),
            "not_runnable": len(self.not_runnable),
            "steps": [s.to_dict() for s in self.steps],
        }


# ── 스텝 준비 ──────────────────────────────────────────────────────────────
_EXPRESSION_RE = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def step_is_runnable(step: dict[str, Any]) -> tuple[bool, str]:
    """이 스텝을 로컬에서 실행할 수 있는가. 불가 사유를 함께 돌려준다."""
    if not isinstance(step, dict):
        return False, "스텝이 매핑이 아님"
    if step.get("uses"):
        return False, f"액션 스텝(환경 전제): {step['uses']}"
    run = step.get("run")
    if not isinstance(run, str) or not run.strip():
        return False, "run 스크립트 없음"
    if _EXPRESSION_RE.search(run):
        # ${{ }} 표현식은 러너 컨텍스트(시크릿·이벤트 페이로드)를 요구한다.
        # 임의로 빈 문자열을 넣으면 *다른 명령*을 돌리고 그 결과를 이 스텝의 것으로
        # 보고하게 된다 — 위장이므로 실행하지 않는다.
        return False, "GitHub 식(${{ }}) 포함 — 러너 컨텍스트 필요"
    if step.get("if"):
        return False, f"스텝 조건 if 보유(평가 생략): {str(step['if'])[:60]}"
    return True, ""


def step_working_directory(job: dict[str, Any], step: dict[str, Any], repo_root: Path) -> Path:
    """잡 defaults와 스텝 오버라이드를 합쳐 실행 디렉터리를 정한다(acceptance ⑤ 계승)."""
    wd = None
    defaults = (job.get("defaults") or {}).get("run") or {}
    if isinstance(defaults.get("working-directory"), str):
        wd = defaults["working-directory"]
    if isinstance(step.get("working-directory"), str):
        wd = step["working-directory"]
    return (repo_root / wd) if wd else repo_root


def step_env(
    job: dict[str, Any], step: dict[str, Any], prepend_path: list[str] | None = None
) -> dict[str, str]:
    """잡 env + 스텝 env. 식이 든 값은 넣지 않는다(잘못된 값으로 돌리느니 비운다).

    `prepend_path`는 CI의 `actions/setup-python`이 하는 일을 대신한다 — 그 스텝은 액션이라
    미러가 실행하지 않으므로, 지정하지 않으면 잡이 *호스트 기본 인터프리터*로 돌아간다.
    그러면 CI와 다른 파이썬으로 판정하게 되고, 그 결과는 이 잡의 것이 아니다.
    """
    env = dict(os.environ)
    if prepend_path:
        env["PATH"] = os.pathsep.join([*prepend_path, env.get("PATH", "")])
    for source in (job.get("env") or {}, step.get("env") or {}):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(value, (str, int, float, bool)):
                text = str(value)
                if not _EXPRESSION_RE.search(text):
                    env[str(key)] = text
    return env


# ── 실행 ───────────────────────────────────────────────────────────────────
def run_step(
    job: dict[str, Any],
    step: dict[str, Any],
    repo_root: Path,
    timeout: int,
    log_handle=None,
    prepend_path: list[str] | None = None,
) -> StepResult:
    """스텝 하나를 bash로 실행한다. 실패해도 원인이 남도록 stderr 꼬리를 보존한다."""
    name = str(step.get("name") or "(이름 없음)")
    runnable, reason = step_is_runnable(step)
    if not runnable:
        return StepResult(name=name, status=NOT_RUNNABLE, reason=reason)

    cwd = step_working_directory(job, step, repo_root)
    if not cwd.is_dir():
        return StepResult(name=name, status=NOT_RUNNABLE, reason=f"작업 디렉터리 없음: {cwd}")

    started = time.monotonic()
    try:
        proc = subprocess.run(
            # GitHub Actions의 bash 기본과 정확히 맞춘다: `bash --noprofile --norc -eo pipefail`.
            # `-u`를 더하면 CI보다 엄격해져 **거짓 실패**를 내고, 거짓 실패는 없는 회귀를
            # 쫓게 만들어 통과보다 비싸다(2026-09-07 축).
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            cwd=cwd,
            env=step_env(job, step, prepend_path),
            capture_output=True,
            timeout=timeout,
        )
        code = proc.returncode
        stderr = proc.stderr.decode("utf-8", errors="replace")
        stdout = proc.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - started
        result = StepResult(
            name=name,
            status=FAILED,
            exit_code=None,
            duration_s=duration,
            reason=f"타임아웃({timeout}s) — 멈춘 사실 자체가 증거다",
        )
        _flush_step(result, log_handle)
        return result

    duration = time.monotonic() - started
    result = StepResult(
        name=name,
        status=PASSED if code == 0 else FAILED,
        exit_code=code,
        duration_s=duration,
        stderr_tail=(stderr or stdout),
    )
    _flush_step(result, log_handle)
    return result


def _flush_step(result: StepResult, log_handle) -> None:
    """스텝마다 즉시 기록한다 — 중간에 멈춰도 거기까지가 남는다."""
    if log_handle is None:
        return
    log_handle.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
    log_handle.flush()


def run_job(
    workflow: dict[str, Any],
    job_name: str,
    repo_root: Path,
    timeout: int = DEFAULT_STEP_TIMEOUT,
    log_handle=None,
    prepend_path: list[str] | None = None,
) -> JobResult:
    """잡 하나의 스텝을 순서대로 실행한다.

    앞 스텝이 실패하면 뒤 스텝은 **실행하지 않고 skipped로 계상**한다 — CI의 실제 동작이며,
    이 숫자가 곧 "이번 실행에서 아무것도 모르는 검사의 수"다(2026-09-10 축).
    """
    jobs = coverage.enumerate_jobs(workflow)
    if job_name not in jobs:
        raise MirrorUsageError(f"ci.yml에 없는 잡 이름: {job_name}")
    job = jobs[job_name]
    steps = job.get("steps") or []
    if not steps:
        raise MirrorUsageError(f"잡 '{job_name}'의 스텝 파싱 0건 — 통과가 아니라 실패다")

    result = JobResult(name=job_name)
    failed = False
    for step in steps:
        if failed:
            result.steps.append(
                StepResult(
                    name=str(step.get("name") or "(이름 없음)"),
                    status=SKIPPED_AFTER_FAILURE,
                    reason="앞 스텝 실패로 미실행 — 이 검사에 대해서는 아무것도 모른다",
                )
            )
            continue
        step_result = run_step(job, step, repo_root, timeout, log_handle, prepend_path)
        result.steps.append(step_result)
        if step_result.status == FAILED:
            failed = True
    return result


# ── 결과 저장·조회 ─────────────────────────────────────────────────────────
def current_commit(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, timeout=30
    )
    if proc.returncode != 0:
        return "unknown"
    return proc.stdout.decode("utf-8", errors="replace").strip()


def build_payload(
    jobs: list[JobResult],
    repo_root: Path,
    workflow_path: Path,
    prepend_path: list[str] | None = None,
) -> dict[str, Any]:
    commit = current_commit(repo_root)
    return {
        "run_id": f"{commit[:12]}-{int(time.time())}",
        "commit": commit,
        "workflow": str(workflow_path),
        "prepend_path": list(prepend_path or []),
        "jobs": [j.to_dict() for j in jobs],
        "exit": 1 if any(j.exit_code for j in jobs) else 0,
    }


def save_payload(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def verdict_for_commit(path: Path, commit: str) -> tuple[bool, str]:
    """`backlog.py done` 프리플라이트용 — 이 커밋에 대한 미러 결과가 있고 통과했는가.

    없거나 커밋이 다르면 "모른다"이며, 그 사실을 문장으로 돌려준다. 호출측이 이것을
    통과로 접지 않도록 bool과 사유를 함께 낸다.
    """
    payload = load_payload(path)
    if payload is None:
        return False, f"CI 미러 결과 없음({path}) — 이 변경에 대해 어느 잡도 돌리지 않았다"
    recorded = str(payload.get("commit", ""))
    if recorded != commit:
        return False, (
            f"CI 미러 결과가 다른 커밋의 것이다(기록 {recorded[:12]} ≠ 현재 {commit[:12]}) — "
            f"이번 변경은 측정되지 않았다"
        )
    if payload.get("exit") != 0:
        failed_jobs = [j["name"] for j in payload.get("jobs", []) if j.get("exit")]
        return False, f"CI 미러가 실패로 끝났다(잡: {', '.join(failed_jobs) or '?'})"
    names = [j["name"] for j in payload.get("jobs", [])]
    return True, f"CI 미러 통과 — 잡 {len(names)}건: {', '.join(names)}"


# ── 출력 ───────────────────────────────────────────────────────────────────
_STATUS_MARK = {
    PASSED: "✔",
    FAILED: "✗",
    SKIPPED_AFTER_FAILURE: "⃠",
    NOT_RUNNABLE: "–",
}


def render(jobs: list[JobResult]) -> str:
    lines: list[str] = []
    for job in jobs:
        lines.append(f"── {job.name} (exit {job.exit_code})")
        for step in job.steps:
            mark = _STATUS_MARK.get(step.status, "?")
            suffix = ""
            if step.status == PASSED:
                suffix = f"  {step.duration_s:.1f}s"
            elif step.status == FAILED:
                suffix = f"  exit={step.exit_code} {step.reason}".rstrip()
            elif step.reason:
                suffix = f"  {step.reason}"
            lines.append(f"  {mark} {step.name}{suffix}")
        if job.skipped_after_failure:
            lines.append(
                f"  ⚠ 앞 스텝 실패로 미실행 {len(job.skipped_after_failure)}건 — "
                f"이 검사들에 대해서는 아무것도 모른다"
            )
        if job.not_runnable:
            lines.append(
                f"  ⓘ 로컬 실행 대상 아님 {len(job.not_runnable)}건(액션·식·조건 스텝) — "
                f"통과로 계상하지 않는다"
            )
        lines.append("")
    return "\n".join(lines)


# ── 서브커맨드 ─────────────────────────────────────────────────────────────
def _resolve_jobs(args: argparse.Namespace, workflow: dict[str, Any], repo_root: Path) -> list[str]:
    """--job 지정이 없으면 HARN-109 열거기로 '봐야 하는 잡'을 계산한다."""
    if args.job:
        return list(args.job)
    changed = coverage.changed_files_from_git(args.diff_base, repo_root)
    scopes = coverage.classify_jobs(workflow, changed)
    required = coverage.jobs_to_cover(scopes)
    by_name = {s.name: s for s in scopes}
    runnable = [n for n in required if by_name[n].env.reproducible_locally]
    skipped = [n for n in required if n not in runnable]
    if skipped:
        print(f"ⓘ 재현 불가라 미러 대상에서 제외: {', '.join(skipped)} (CI가 최종 판정)")
    return runnable


def cmd_run(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    workflow = coverage.load_workflow(args.workflow)
    job_names = _resolve_jobs(args, workflow, repo_root)
    if not job_names:
        raise MirrorUsageError("실행 대상 잡 0건 — 스캔 0건은 통과가 아니다")

    log_path = args.result.with_suffix(".steps.ndjson")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[JobResult] = []
    with log_path.open("w", encoding="utf-8") as handle:
        for name in job_names:
            print(f"▶ {name}", flush=True)
            results.append(
                run_job(workflow, name, repo_root, args.timeout, handle, args.prepend_path)
            )

    payload = build_payload(results, repo_root, args.workflow, args.prepend_path)
    save_payload(payload, args.result)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(results))
        print(f"결과 저장: {args.result} (commit {payload['commit'][:12]})")
        failed = [j.name for j in results if j.exit_code]
        print(f"✗ 실패 잡: {', '.join(failed)}" if failed else "✔ 전 잡 통과")
    return int(payload["exit"])


def cmd_verdict(args: argparse.Namespace) -> int:
    ok, reason = verdict_for_commit(args.result, current_commit(Path.cwd()))
    print(("✔ " if ok else "⚠ ") + reason)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ci_mirror.py",
        description="CI 잡 스텝을 로컬에서 그대로 실행하고 skipped 수를 센다 (HARN-119)",
    )
    p.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    p.add_argument("--result", type=Path, default=DEFAULT_RESULT_PATH, help="결과 JSON 경로")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="잡 실행 (미지정 시 변경이 닿는 잡을 자동 계산)")
    pr.add_argument("--job", action="append", default=[], help="실행할 잡 이름(반복 지정)")
    pr.add_argument("--diff-base", default="origin/main")
    pr.add_argument("--timeout", type=int, default=DEFAULT_STEP_TIMEOUT)
    pr.add_argument(
        "--prepend-path",
        action="append",
        default=[],
        help="PATH 앞에 둘 디렉터리(반복 지정) — CI의 setup-python을 대신한다. "
        "지정하지 않으면 호스트 기본 인터프리터로 돌아 CI와 다른 판정을 낸다",
    )
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_run)

    pv = sub.add_parser("verdict", help="현재 커밋에 대한 미러 결과가 있고 통과했는지")
    pv.set_defaults(func=cmd_verdict)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except MirrorUsageError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except coverage.ScanEmptyError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
