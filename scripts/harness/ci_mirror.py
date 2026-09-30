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
  · 실패 *원인*을 남긴다 — exit code만이 아니라 stderr·stdout 꼬리를 함께 기록. GitHub 형식
    오류(`::error::`)는 stdout으로 나오므로 stderr만 남기면 원인이 통째로 사라진다(HARN-162)
  · 모든 서브프로세스에 타임아웃 — 무한 대기로 측정 회차를 태우지 않는다
  · 지금 보는 것이 이번 실행인가 — 결과 JSON에 기준 커밋 해시를 박는다
  · 스텝은 **GitHub가 그 스텝에 쓰는 셸**로 돌린다 — `shell:` 키가 없으면 `bash -e`(pipefail
    없음), `shell: bash`면 `bash --noprofile --norc -eo pipefail`이다. 둘은 다르며 미러가 CI보다
    엄격하면 거짓 실패가 난다(HARN-162 — 아래 `step_shell_argv`)

범위:
  `uses:` 액션 스텝(체크아웃·setup-python 등)은 로컬에서 실행하지 않는다. "환경 전제"로
  표기하며 통과로 계상하지 않는다 — 실행하지 않은 것을 실행했다고 세는 것이 빠뜨리는 것보다
  나쁘다. 서비스 컨테이너·docker 빌드가 필요한 잡도 같은 이유로 실행 대상에서 제외된다
  (HARN-109가 '재현 불가'로 판정한 잡).

  환경 전제와 **미실행**은 다르다(HARN-180). 액션 스텝은 원래 로컬 대상이 아니지만, `run`
  스텝이 식·조건·작업 디렉터리 때문에 돌지 못했다면 그것은 CI에서는 도는 *검사*를 이번에
  빠뜨린 것이다. 미실행이 1건이라도 있으면 "전 잡 통과"라고 말하지 않는다 — 안 돌린 검사와
  통과한 검사를 같은 화면에 두면 사람이 통과로 읽는다(2026-09-27 EOS-26 실측: OPS-24 드리프트
  게이트 2개가 건너뛰어졌는데 최종 줄은 "✔ 전 잡 통과"였다).

exit code: 0 전 스텝 통과 · 1 실패 스텝 존재 · 2 사용 오류(잡 이름 오타·파싱 0건
  · 자동 선택의 판정 대상 변경 파일 0건 · `--stdin` 없는 파이프 입력 — HARN-172)
  · 3 실행한 스텝은 전부 통과했지만 미실행 검사 스텝 존재(HARN-180 — 통과가 아니다)
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

#: 결과 JSON 형식 판. 2 = 미실행(`not_executed`)을 환경 전제와 분리해 기록하는 형식(HARN-180).
#: 판이 다른 결과는 미실행 수를 판정할 수 없으므로 verdict가 "모른다"로 답한다 — 옛 형식은
#: 건너뛴 검사를 환경 전제와 같은 칸에 넣었기 때문이다.
RESULT_SCHEMA = 2

#: 실행한 스텝은 전부 통과했지만 미실행 검사 스텝이 있다 — 통과(0)도 실패(1)도 아니다.
#: 실패와 코드를 나누는 이유는 처방이 다르기 때문이다: 실패는 고칠 대상이고, 미실행은
#: 목록을 읽고 CI 판정에 맡길 대상이다(같은 코드면 어느 쪽인지 출력을 다시 읽어야 한다).
EXIT_NOT_EXECUTED = 3

PASSED = "passed"
FAILED = "failed"
SKIPPED_AFTER_FAILURE = "skipped_after_failure"
#: 환경 전제 — 액션 스텝(`uses:`). 원래 로컬 실행 대상이 아니다(체크아웃은 이미 된 트리가,
#: setup-python은 `--prepend-path`가 대신한다). 통과로도 미실행 검사로도 세지 않는다.
NOT_RUNNABLE = "not_runnable"
#: 미실행 — CI에서는 도는 `run` 스텝인데 이번 로컬 실행에서 돌리지 못했다(식·조건·작업
#: 디렉터리). 이 검사에 대해서는 아무것도 모른다 — 최종 줄과 verdict가 그 수를 드러낸다.
NOT_EXECUTED = "not_executed"


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
    #: 실패 스텝만 채운다(통과 스텝의 stdout은 설치 로그 같은 소음이라 JSON만 부풀린다).
    stdout_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 2),
            "reason": self.reason,
            "stderr_tail": self.stderr_tail[-800:],
            "stdout_tail": self.stdout_tail[-800:],
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
    def not_executed(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == NOT_EXECUTED]

    @property
    def exit_code(self) -> int:
        """잡 단위는 실패 여부만 말한다(0/1). 미실행은 실행 전체 판정(`payload_exit`)이 센다."""
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
            "not_executed": len(self.not_executed),
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


def not_run_status(step: Any) -> str:
    """돌리지 않은 스텝이 '환경 전제'인가 '미실행 검사'인가 (HARN-180).

    액션 스텝만 환경 전제다. 그 밖에 돌지 않은 스텝(식·조건·작업 디렉터리·run 없음)은
    CI에서는 도는 무언가를 이번에 빠뜨린 것이므로 미실행으로 센다 — 모르는 쪽으로 분류해야
    통과로 새지 않는다.
    """
    if isinstance(step, dict) and step.get("uses"):
        return NOT_RUNNABLE
    return NOT_EXECUTED


#: `${{ github.workspace }}` — 러너 작업공간의 절대경로. 중괄호 안 공백은 GitHub 문법상 자유다.
_WORKSPACE_EXPR_RE = re.compile(r"\$\{\{\s*github\.workspace\s*\}\}")


def step_working_directory(
    job: dict[str, Any], step: dict[str, Any], repo_root: Path
) -> tuple[Path | None, str]:
    """잡 defaults와 스텝 오버라이드를 합쳐 실행 디렉터리를 정한다(acceptance ⑤ 계승).

    `${{ github.workspace }}`는 저장소 루트로 해석한다(HARN-180). 새 가정이 아니다 — 미러는
    상대 working-directory를 이미 저장소 루트 기준으로 풀고 있고, GitHub도 상대경로를
    github.workspace 기준으로 풀며 actions/checkout은 `path:`가 없으면 그 자리에 받는다
    (2026-09-27 실측: 워크플로 7개 전부 checkout `path:` 0건). 둘은 같은 전제다.

    그 밖의 식은 해석하지 않고 (None, 사유)를 돌려준다 — 추측한 경로에서 돌린 결과를 이
    스텝의 것으로 보고하면 위장이다. 실제로 OPS-24 게이트는 잡 기본값(src/backend)에서 돌리면
    FileNotFoundError로 거짓 실패한다.
    """
    wd = None
    defaults = (job.get("defaults") or {}).get("run") or {}
    if isinstance(defaults.get("working-directory"), str):
        wd = defaults["working-directory"]
    if isinstance(step.get("working-directory"), str):
        wd = step["working-directory"]
    if not wd:
        return repo_root, ""
    root_text = str(repo_root.resolve())
    # 치환값을 함수로 넘긴다 — 문자열로 넘기면 Windows 경로의 `\U` 같은 역슬래시가 치환
    # 이스케이프로 해석돼 re.error가 난다.
    resolved = _WORKSPACE_EXPR_RE.sub(lambda _match: root_text, wd)
    if _EXPRESSION_RE.search(resolved):
        return None, f"작업 디렉터리에 해석하지 않는 GitHub 식: {wd}"
    # 치환 결과가 절대경로면 `/` 결합은 오른쪽을 그대로 쓴다.
    return repo_root / resolved, ""


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


#: `shell:` 키가 없는 스텝(리눅스)에 GitHub가 실제로 쓰는 호출 — `bash -e {0}`. **pipefail이 없다.**
_SHELL_ARGV_UNSET = ["bash", "-e"]
#: `shell: bash`를 **명시**했을 때의 호출. 이쪽만 pipefail이 켜진다.
_SHELL_ARGV_BASH = ["bash", "--noprofile", "--norc", "-eo", "pipefail"]


def _run_defaults(container: Any) -> dict[str, Any]:
    """워크플로·잡의 `defaults.run` 매핑. 모양이 다르면 빈 매핑(호출측이 '선언 없음'으로 읽는다)."""
    defaults = container.get("defaults") if isinstance(container, dict) else None
    run = defaults.get("run") if isinstance(defaults, dict) else None
    return run if isinstance(run, dict) else {}


def step_shell_argv(
    job: dict[str, Any], step: dict[str, Any], default_shell: Any = None
) -> tuple[list[str] | None, str]:
    """이 스텝에 GitHub가 쓰는 셸 호출 인자열. 재현하지 않는 셸이면 (None, 사유) (HARN-162).

    우선순위는 GitHub와 같다: 스텝 `shell` > 잡 `defaults.run.shell` > 워크플로
    `defaults.run.shell`(`default_shell`). 선언이 하나도 없으면 `bash -e`이고, 명시적
    `shell: bash`만 `-o pipefail`이 붙는다 — 이 둘을 같은 것으로 다루면 미러가 CI보다 엄격해져
    거짓 실패를 낸다(2026-09-22 실측: webapp 잡의 `leak=$(grep … | wc -l)`이 no-match에서 CI는
    통과인데 미러는 pipefail 때문에 exit 1).

    bash 두 형태 밖의 셸(`pwsh`·`python`·`sh`·사용자 정의 템플릿)은 (None, 사유)를 돌려준다.
    모르는 셸을 bash로 돌리면 그 결과는 그 스텝의 것이 아니므로 실행하지 않고 사유를 남긴다 —
    호출측이 미실행으로 센다. 선언 값의 판별은 `is None`이다(빈 문자열도 '선언'이다).
    """
    declared = step.get("shell")
    if declared is None:
        declared = _run_defaults(job).get("shell")
    if declared is None:
        declared = default_shell
    if declared is None:
        return list(_SHELL_ARGV_UNSET), ""
    if declared == "bash":
        return list(_SHELL_ARGV_BASH), ""
    return None, (
        f"미러가 재현하지 않는 셸(shell: {declared!r}) — "
        f"다른 셸로 돌린 결과는 이 스텝의 것이 아니다"
    )


# ── 실행 ───────────────────────────────────────────────────────────────────
def run_step(
    job: dict[str, Any],
    step: dict[str, Any],
    repo_root: Path,
    timeout: int,
    log_handle=None,
    prepend_path: list[str] | None = None,
    default_shell: Any = None,
) -> StepResult:
    """스텝 하나를 GitHub와 같은 셸로 실행한다. 실패 원인이 남도록 stderr·stdout 꼬리를 보존한다."""
    name = str(step.get("name") or "(이름 없음)")
    runnable, reason = step_is_runnable(step)
    if not runnable:
        return StepResult(name=name, status=not_run_status(step), reason=reason)

    shell_argv, shell_reason = step_shell_argv(job, step, default_shell)
    if shell_argv is None:
        return StepResult(name=name, status=NOT_EXECUTED, reason=shell_reason)

    cwd, wd_reason = step_working_directory(job, step, repo_root)
    if cwd is None:
        return StepResult(name=name, status=NOT_EXECUTED, reason=wd_reason)
    if not cwd.is_dir():
        return StepResult(name=name, status=NOT_EXECUTED, reason=f"작업 디렉터리 없음: {cwd}")

    started = time.monotonic()
    try:
        proc = subprocess.run(
            # 셸 인자는 스텝의 `shell` 선언이 정한다(`step_shell_argv`) — 한 가지로 고정하지 않는다.
            # CI보다 엄격한 플래그(`-u`, 선언 없는 스텝의 pipefail)는 **거짓 실패**를 내고, 거짓
            # 실패는 없는 회귀를 쫓게 만들어 통과보다 비싸다(2026-09-07 축).
            [*shell_argv, "-c", step["run"]],
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
        stderr_tail=stderr,
        # `::error::` 같은 GitHub 형식 오류는 stdout으로 나온다 — stderr만 남기면 원인이 사라진다.
        stdout_tail=stdout if code != 0 else "",
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

    # 워크플로 최상위 `defaults.run.shell`은 잡·스텝 선언이 없을 때의 기본이다. 지금 ci.yml에는
    # 없지만, 생기면 조용히 무시된 채 다른 셸로 돌지 않게 여기서 읽어 넘긴다.
    default_shell = _run_defaults(workflow).get("shell")

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
        step_result = run_step(
            job, step, repo_root, timeout, log_handle, prepend_path, default_shell
        )
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


def payload_exit(jobs: list[JobResult]) -> int:
    """실행 전체의 판정 코드 — 실패가 미실행보다 앞선다(실패는 그 자체로 고칠 대상)."""
    if any(j.exit_code for j in jobs):
        return 1
    if any(j.not_executed for j in jobs):
        return EXIT_NOT_EXECUTED
    return 0


def build_payload(
    jobs: list[JobResult],
    repo_root: Path,
    workflow_path: Path,
    prepend_path: list[str] | None = None,
) -> dict[str, Any]:
    commit = current_commit(repo_root)
    return {
        "schema": RESULT_SCHEMA,
        "run_id": f"{commit[:12]}-{int(time.time())}",
        "commit": commit,
        "workflow": str(workflow_path),
        "prepend_path": list(prepend_path or []),
        "jobs": [j.to_dict() for j in jobs],
        "not_executed": sum(len(j.not_executed) for j in jobs),
        "exit": payload_exit(jobs),
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


VERDICT_PASS = "pass"
#: 실행한 스텝은 전부 통과 · 미실행 검사 스텝 존재 — 통과가 아니다(HARN-180).
VERDICT_NOT_EXECUTED = "not_executed"
VERDICT_FAIL = "fail"
#: 결과 없음·다른 커밋·형식 불일치·잡 0건 — 측정되지 않았다.
VERDICT_UNKNOWN = "unknown"

#: 사유 문장에 늘어놓는 미실행 스텝 수 상한 — 넘으면 "외 N건"으로 줄이되 총수는 항상 말한다.
_LISTED_NOT_EXECUTED = 8


@dataclass
class Verdict:
    state: str
    reason: str
    #: "잡 › 스텝 (사유)" 목록 — 호출측이 무엇을 모르는지 이름으로 말할 수 있게 한다.
    not_executed: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """verdict 서브커맨드의 종료 코드. run과 같은 체계다(0 통과 · 3 미실행 · 1 그 밖)."""
        if self.state == VERDICT_PASS:
            return 0
        if self.state == VERDICT_NOT_EXECUTED:
            return EXIT_NOT_EXECUTED
        return 1


def mirror_verdict(path: Path, commit: str) -> Verdict:
    """이 커밋에 대한 미러 결과를 네 상태로 판정한다 — 통과·미실행·실패·모름.

    없거나 커밋이 다르면 "모른다"이며, 그 사실을 문장으로 돌려준다. 미실행을 통과와 따로
    두는 이유는 HARN-180 실측 때문이다: 건너뛴 검사 2개가 있었는데 결과가 exit 0이었고,
    `backlog.py done`의 경고가 그것을 통과로 읽었다. 미실행 수는 스텝 기록에서 직접 센다 —
    최상위 요약값보다 스텝 기록이 원자료다.
    """
    payload = load_payload(path)
    if payload is None:
        return Verdict(
            VERDICT_UNKNOWN, f"CI 미러 결과 없음({path}) — 이 변경에 대해 어느 잡도 돌리지 않았다"
        )
    recorded = str(payload.get("commit", ""))
    if recorded != commit:
        return Verdict(
            VERDICT_UNKNOWN,
            f"CI 미러 결과가 다른 커밋의 것이다(기록 {recorded[:12]} ≠ 현재 {commit[:12]}) — "
            f"이번 변경은 측정되지 않았다",
        )
    if payload.get("schema") != RESULT_SCHEMA:
        return Verdict(
            VERDICT_UNKNOWN,
            f"CI 미러 결과 형식이 이 도구와 다르다(schema {payload.get('schema')!r} ≠ "
            f"{RESULT_SCHEMA}) — 옛 형식은 건너뛴 검사를 환경 전제와 구분하지 않아 미실행 수를 "
            f"판정할 수 없다. 다시 돌려라",
        )
    raw_jobs = payload.get("jobs")
    # 스텝 기록이 빠진 잡을 "미실행 0건"으로 읽으면 모르는 것을 아니라고 접는 것이다.
    if not isinstance(raw_jobs, list) or not all(
        isinstance(j, dict) and isinstance(j.get("steps"), list) for j in raw_jobs
    ):
        # 손상된 결과로 done 프리플라이트가 예외를 내며 죽으면 판정 대신 크래시가 남는다.
        return Verdict(VERDICT_UNKNOWN, "CI 미러 결과의 잡·스텝 형식이 깨졌다 — 다시 돌려라")
    jobs: list[dict[str, Any]] = raw_jobs
    if not jobs:
        return Verdict(VERDICT_UNKNOWN, "CI 미러 결과에 잡이 0건이다 — 스캔 0건은 통과가 아니다")
    names = [str(j.get("name", "?")) for j in jobs]
    failed_jobs = [str(j.get("name", "?")) for j in jobs if j.get("exit")]
    if failed_jobs or payload.get("exit") not in (0, EXIT_NOT_EXECUTED):
        return Verdict(
            VERDICT_FAIL, f"CI 미러가 실패로 끝났다(잡: {', '.join(failed_jobs) or '?'})"
        )
    not_executed = [
        f"{j.get('name', '?')} › {s.get('name', '?')} ({s.get('reason', '')})"
        for j in jobs
        for s in j.get("steps") or []
        if isinstance(s, dict) and s.get("status") == NOT_EXECUTED
    ]
    if not_executed:
        shown = not_executed[:_LISTED_NOT_EXECUTED]
        more = len(not_executed) - len(shown)
        listing = "\n".join(f"    · {item}" for item in shown)
        if more:
            listing += f"\n    · 외 {more}건"
        return Verdict(
            VERDICT_NOT_EXECUTED,
            f"CI 미러: 실행한 스텝은 전부 통과 · 미실행 {len(not_executed)}건 — 전 잡 통과가 "
            f"아니다(잡 {len(names)}건: {', '.join(names)})\n{listing}",
            not_executed,
        )
    return Verdict(VERDICT_PASS, f"CI 미러 통과 — 잡 {len(names)}건: {', '.join(names)}")


def verdict_for_commit(path: Path, commit: str) -> tuple[bool, str]:
    """`mirror_verdict`를 bool로 접은 호환 창구 — 미실행은 **통과가 아니다**(False).

    bool로 접으면 미실행과 실패가 같은 값이 되므로, 둘을 다르게 안내해야 하는 호출측
    (`backlog.py done`)은 `mirror_verdict`를 직접 쓴다.
    """
    verdict = mirror_verdict(path, commit)
    return verdict.state == VERDICT_PASS, verdict.reason


# ── 출력 ───────────────────────────────────────────────────────────────────
_STATUS_MARK = {
    PASSED: "✔",
    FAILED: "✗",
    SKIPPED_AFTER_FAILURE: "⃠",
    NOT_RUNNABLE: "–",
    NOT_EXECUTED: "○",
}


def render(jobs: list[JobResult]) -> str:
    lines: list[str] = []
    for job in jobs:
        # 잡 머리말에도 미실행 수를 붙인다 — "(exit 0)"만 있으면 그 줄이 통과로 읽힌다.
        header_tail = f" · 미실행 {len(job.not_executed)}" if job.not_executed else ""
        lines.append(f"── {job.name} (exit {job.exit_code}{header_tail})")
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
        if job.not_executed:
            lines.append(
                f"  ⚠ 미실행 {len(job.not_executed)}건(식·조건·작업 디렉터리) — CI에서는 도는 "
                f"검사인데 이번에 돌지 않았다. 통과로 계상하지 않는다"
            )
        if job.not_runnable:
            lines.append(
                f"  ⓘ 환경 전제 {len(job.not_runnable)}건(액션 스텝) — 로컬 실행 대상이 아니며 "
                f"통과로 계상하지 않는다"
            )
        lines.append("")
    return "\n".join(lines)


def final_line(jobs: list[JobResult]) -> str:
    """실행 전체의 한 줄 판정. 미실행이 있으면 "전 잡 통과"라고 쓰지 않는다(HARN-180)."""
    failed = [j.name for j in jobs if j.exit_code]
    by_job = [f"{j.name} {len(j.not_executed)}" for j in jobs if j.not_executed]
    count = sum(len(j.not_executed) for j in jobs)
    if failed:
        tail = f" · 미실행 {count}건({', '.join(by_job)})" if count else ""
        return f"✗ 실패 잡: {', '.join(failed)}{tail}"
    if count:
        return (
            f"⚠ 실행한 스텝은 전부 통과 · 미실행 {count}건({', '.join(by_job)}) — 전 잡 통과가 "
            f"아니다(exit {EXIT_NOT_EXECUTED}). 미실행 스텝은 로컬에서 돌지 않았다: 직접 돌리거나 "
            f"CI 판정으로 넘긴다고 적어라"
        )
    return "✔ 전 잡 통과"


# ── 서브커맨드 ─────────────────────────────────────────────────────────────
def _resolve_jobs(args: argparse.Namespace, workflow: dict[str, Any], repo_root: Path) -> list[str]:
    """--job 지정이 없으면 HARN-109 열거기로 '봐야 하는 잡'을 계산한다."""
    if args.job:
        return list(args.job)
    # 판정 입력은 scope와 **같은 창구**로 정한다(HARN-172 ④) — 직접 git diff를 부르면 변경 0건이
    # 상시 잡만 고른 "✔ 전 잡 통과"가 되고, 파이프 입력은 조용히 버려진다(2026-09-25 사고 형태).
    info = coverage.resolve_changed_files(
        changed_file=[],
        use_stdin=args.stdin,
        diff_base=args.diff_base,
        repo_root=repo_root,
        allow_empty=args.allow_empty,
    )
    for line in coverage.render_changed_input(info):
        print(line)
    # 최종 줄 뒤에 반복한다 — 결과를 tail로 잘라 읽어도 미커밋 누락이 보이게(cmd_run이 출력).
    args.input_warning_tail = coverage.input_warning_tail(info)
    changed = info.files
    scopes = coverage.classify_jobs(workflow, changed)
    required = coverage.jobs_to_cover(scopes)
    by_name = {s.name: s for s in scopes}
    runnable = [n for n in required if by_name[n].env.reproducible_locally]
    skipped = [n for n in required if n not in runnable]
    if skipped:
        print(f"ⓘ 재현 불가라 미러 대상에서 제외: {', '.join(skipped)} (CI가 최종 판정)")
    # 경로 필터 잡은 이 미러의 잡 선택이 대신한다(HARN-180) — 위 required가 바로 그 잡의 filter
    # 스텝을 정본으로 읽어 계산한 결과다. 돌리면 filter 스텝이 GitHub 식 때문에 매번 미실행으로
    # 세어져 자동 선택 실행이 전부 exit 3이 된다 — 상시 켜진 경고는 보호가 아니라 소음이다.
    # `--job`으로 직접 지정하면 돌리고 미실행을 그대로 보고한다(위 분기).
    if coverage.FILTER_JOB in runnable:
        runnable.remove(coverage.FILTER_JOB)
        print(
            f"ⓘ {coverage.FILTER_JOB} 잡은 미러 대상에서 제외: 경로 필터 계산 잡이며 이 미러의 "
            f"잡 선택이 같은 정본(그 잡의 filter 스텝)을 읽어 대신했다 (CI가 최종 판정)"
        )
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
        print(final_line(results))
        if getattr(args, "input_warning_tail", None):
            print(args.input_warning_tail)
    return int(payload["exit"])


def cmd_verdict(args: argparse.Namespace) -> int:
    """0 통과 · 3 실행분 통과+미실행 존재 · 1 실패·결과 없음·다른 커밋·형식 불일치.

    종료 코드를 바꾼 근거(HARN-180 ③): 이 저장소의 판정 규칙은 "exit code로 판정한다"이므로,
    미실행이 있는데 0을 내면 문장을 아무리 바꿔도 코드를 읽는 쪽에는 통과로 보인다 — 2026-09-27
    실측이 정확히 그 형태였다. 그렇다고 1(실패)로 접지 않는 이유는 처방이 달라서다.
    `backlog.py done`은 이 판정을 경고로만 쓴다(1단계 warn — block 승격은 HARN-173/HARN-122
    절차 소관). 지금 막으면 조건 스텝(`if:`)처럼 로컬에서 원리상 평가할 수 없는 검사를 가진
    잡이 영구히 done을 막아, 사람이 경고 자체를 끄게 된다.
    """
    verdict = mirror_verdict(args.result, current_commit(Path.cwd()))
    print(("✔ " if verdict.state == VERDICT_PASS else "⚠ ") + verdict.reason)
    return verdict.exit_code


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
    # HARN-172 — 자동 잡 선택의 판정 입력 규칙은 ci_job_coverage scope와 같다.
    pr.add_argument(
        "--stdin",
        action="store_true",
        help="--job 미지정 시 표준 입력의 경로 목록으로 잡을 고른다(없으면 파이프 입력은 거부)",
    )
    pr.add_argument(
        "--allow-empty",
        action="store_true",
        help="변경 파일 0건을 의도한 판정으로 허용(상시 잡만 실행) — 없으면 0건은 exit 2",
    )
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

    pv = sub.add_parser(
        "verdict",
        help="현재 커밋에 대한 미러 결과가 있고 통과했는지 (0 통과 · 3 미실행 존재 · 1 그 밖)",
    )
    pv.set_defaults(func=cmd_verdict)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (MirrorUsageError, coverage.InputRejectedError) as exc:
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
