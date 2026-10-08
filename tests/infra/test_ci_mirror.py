"""CI 미러의 계약 동결 — HARN-119 · HARN-180 · HARN-162.

이 파일이 지키는 것:
  · 스텝을 **GitHub가 그 스텝에 쓰는 셸**로 돌리는가 — `shell:` 키 없음은 `bash -e`(pipefail
    없음), `shell: bash`는 `-eo pipefail`, 그 밖의 셸은 실행하지 않고 미실행으로 센다.
    그리고 실패 스텝의 stderr·stdout 꼬리가 모두 남는가 (HARN-162 — 2026-09-22 실측: webapp
    잡의 `leak=$(grep … | wc -l)`이 CI는 통과인데 미러는 pipefail 때문에 exit 1, 원인 미기록)
  · 앞 스텝이 실패하면 뒤 스텝을 **skipped로 계상**하는가 (2026-09-10 축의 핵심)
  · 실행할 수 없는 스텝을 **통과로 세지 않는가** (액션·식·조건 스텝)
  · 잡 이름 오타·스텝 0건을 사용 오류(exit 2)로 거부하는가
  · 출력이 억제·절단된 스텝도 **exit code로만** 판정하는가 (2026-08-09 축)
  · done 프리플라이트가 커밋 불일치를 "모른다"로 말하는가
  · `working-directory`의 `${{ github.workspace }}`를 저장소 루트로 풀어 **실제로 돌리는가**,
    그 밖의 식은 추측하지 않고 미실행으로 남기는가 (HARN-180 ②)
  · 액션 스텝(환경 전제)과 못 돌린 검사 스텝(미실행)을 나누고, 미실행이 있으면 최종 줄·
    verdict·종료 코드가 **통과라고 말하지 않는가** (HARN-180 ③ — 2026-09-27 실측: 건너뛴
    검사 2개가 있었는데 최종 줄은 "✔ 전 잡 통과", verdict는 exit 0이었다)

각 절마다 그 절이 없으면 통과하는 입력을 픽스처로 둔다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIRROR_PATH = _REPO_ROOT / "scripts" / "harness" / "ci_mirror.py"
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_DRIVE_DOC = _REPO_ROOT / ".claude" / "commands" / "drive.md"
_BACKLOG_CLI = _REPO_ROOT / "scripts" / "harness" / "backlog.py"


def _load_mirror():
    sys.path.insert(0, str(_MIRROR_PATH.parent))
    spec = importlib.util.spec_from_file_location("ci_mirror", _MIRROR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_mirror"] = module
    spec.loader.exec_module(module)
    return module


mirror = _load_mirror()


def _wf(steps: list[dict], job_name: str = "demo", **job_extra) -> dict:
    job = {"steps": steps}
    job.update(job_extra)
    return {"jobs": {job_name: job}}


#: 실제 ci.yml(OPS-24 게이트 2개)이 쓰는 형태 그대로.
_WS = "${{ github.workspace }}"


def _assert_workspace_step_runs(module, tmp_path: Path) -> None:
    """HARN-180 ④⑴ — `${{ github.workspace }}` 스텝이 **저장소 루트에서 실제로 돈다**.

    잡 기본값은 하위 디렉터리이고 표식 파일은 루트에만 둔다. 그래서 이 단언은 ⓐ스텝이
    건너뛰어지면(해석 없음) 실패하고 ⓑ잡 기본값에서 돌면(잘못된 해석) `test -f`가 실패한다 —
    두 오답을 각각 가른다. 뮤테이션 테스트가 같은 함수를 변이 모듈에 대고 RED를 확인한다.
    """
    root = tmp_path / "repo"
    (root / "src" / "backend").mkdir(parents=True)
    (root / "root_marker.txt").write_text("루트에만 있다", encoding="utf-8")
    wf = _wf(
        [{"name": "ops24-like", "working-directory": _WS, "run": "test -f root_marker.txt"}],
        defaults={"run": {"working-directory": "src/backend"}},
    )
    step = module.run_job(wf, "demo", root).steps[0]
    assert step.status == module.PASSED, f"스텝이 돌지 않았거나 다른 곳에서 돌았다: {step}"
    assert step.exit_code == 0


def _write_result(path: Path, jobs: list, commit: str = "c" * 40) -> dict:
    """실제 `build_payload` 경로로 결과 JSON을 만든다 — 손으로 쓴 JSON은 형식 드리프트를 못 본다.

    트리 판정은 **안정**으로 명시한다(HARN-194) — 판정 없이 만든 결과는 "지문을 못 잡음"으로
    기록되어 verdict가 측정되지 않은 것으로 답하기 때문이다. 오염 결과는 `new_tainted_*` 테스트가
    실제 실행 경로로 만든다.
    """
    # build_payload가 이 디렉터리에서 git을 부르므로 먼저 있어야 한다(커밋 값은 아래서 덮는다).
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = mirror.build_payload(
        jobs, path.parent, Path("ci.yml"), tree=mirror.TreeCheck(mirror.TREE_STABLE)
    )
    payload["commit"] = commit
    mirror.save_payload(payload, path)
    return payload


def _init_git_repo(root: Path) -> Path:
    """커밋 1건짜리 임시 저장소 — `cmd_run`은 시작·종료 트리 지문을 잡으려고 git을 부른다(HARN-194)."""
    root.mkdir(parents=True, exist_ok=True)
    for argv in (
        ["init", "-q"],
        ["config", "user.name", "t"],
        ["config", "user.email", "t@example.com"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *argv], cwd=root, check=True, capture_output=True)
    (root / ".gitignore").write_text(".claude/cache/\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, capture_output=True)
    return root


def _job(name: str, *steps: tuple[str, str]) -> object:
    """(스텝 이름, 상태) 쌍으로 JobResult를 만든다."""
    return mirror.JobResult(
        name=name,
        steps=[
            mirror.StepResult(name=step_name, status=status, reason=f"{step_name} 사유")
            for step_name, status in steps
        ],
    )


def _assert_not_run_step_is_counted(module, tmp_path: Path, step: dict) -> None:
    """HARN-180 ④⑵ — 못 돌린 검사 스텝 1건이 미실행으로 세어지고, 최종 줄·종료 코드가
    통과라고 말하지 않는다. 대조로 통과 스텝 1건을 함께 둔다(통과를 미실행으로 세는 과잉
    수정도 여기서 걸린다)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    result = module.run_job(_wf([{"name": "ok", "run": "true"}, step]), "demo", tmp_path)
    assert result.steps[0].status == module.PASSED
    assert len(result.not_executed) == 1, f"미실행으로 세지 않았다: {result.steps[-1]}"
    assert module.payload_exit([result]) == 3
    line = module.final_line([result])
    assert not line.startswith("✔") and "미실행 1건" in line, line


def _assert_verdict_names_not_executed(module, tmp_path: Path) -> None:
    """HARN-180 ③ verdict 축 — 미실행 결과는 통과가 아니고 exit 3이며 스텝 이름을 말한다."""
    path = tmp_path / "r.json"
    _write_result(
        path, [_job("j", ("ok", mirror.PASSED), ("건너뛴 게이트", mirror.NOT_EXECUTED))], "a" * 40
    )
    verdict = module.mirror_verdict(path, "a" * 40)
    assert verdict.state == module.VERDICT_NOT_EXECUTED, verdict
    assert verdict.exit_code == 3
    assert "건너뛴 게이트" in verdict.reason


def _write_old_format_result(path: Path) -> None:
    """2026-09-27 실측 결과의 형태 — schema 없음 · 건너뛴 검사가 환경 전제 칸 · exit 0."""
    skipped = {
        "name": "게이트 — 코퍼스 review_status 백필 드리프트 (OPS-24)",
        "status": "not_runnable",
        "reason": "작업 디렉터리 없음: /repo/${{ github.workspace }}",
    }
    payload = {
        "commit": "a" * 40,
        "exit": 0,
        "jobs": [{"name": "declared-unwired-audit", "exit": 0, "steps": [skipped]}],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


#: CI를 막을 수 있어도 "환경 전제"로 세는 것이 정직한 액션 — 준비(체크아웃·런타임 설치)와
#: 보관(산출물 업로드)뿐이다. 검사 액션을 여기에 넣으면 미러가 그 검사를 숨긴다.
_INFRA_ACTIONS = frozenset(
    {
        "actions/checkout",
        "actions/setup-python",
        "actions/setup-node",
        "actions/upload-artifact",
        "subosito/flutter-action",
    }
)


def _blocking_non_infra_actions(workflow: dict) -> list[str]:
    """continue-on-error 없이 CI를 막을 수 있는데 준비·보관용이 아닌 액션 스텝."""
    found: list[str] = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            uses = str(step.get("uses") or "")
            if not uses or step.get("continue-on-error"):
                continue
            if uses.split("@", 1)[0] not in _INFRA_ACTIONS:
                found.append(f"{job_name} › {step.get('name') or uses}")
    return found


def _auto_selected(module, monkeypatch, tmp_path: Path, changed: list[str]) -> list[str]:
    """`--job` 없이 run을 부를 때 고르는 잡 — 실제 ci.yml·실제 열거기로 계산한다."""
    monkeypatch.chdir(_REPO_ROOT)
    workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    args = module.build_parser().parse_args(
        ["--workflow", str(_CI_PATH), "--result", str(tmp_path / "r.json"), "run"]
    )
    monkeypatch.setattr(module.coverage, "changed_files_from_git", lambda base, root: list(changed))
    return module._resolve_jobs(args, workflow, _REPO_ROOT)


def _static_not_executed(job: dict, repo_root: Path, default_shell=None) -> list[str]:
    """돌려 보지 않고도 알 수 있는 미실행 — 원리상 로컬에서 못 도는 run 스텝(식·조건·디렉터리·
    미러가 재현하지 않는 셸). `run_step`의 판정 순서를 그대로 따른다."""
    found: list[str] = []
    for step in job.get("steps") or []:
        runnable, reason = mirror.step_is_runnable(step)
        if not runnable:
            if mirror.not_run_status(step) == mirror.NOT_EXECUTED:
                found.append(f"{step.get('name')}: {reason}")
            continue
        argv, shell_why = mirror.step_shell_argv(job, step, default_shell)
        if argv is None:
            found.append(f"{step.get('name')}: {shell_why}")
            continue
        cwd, why = mirror.step_working_directory(job, step, repo_root)
        if cwd is None or not cwd.is_dir():
            found.append(f"{step.get('name')}: {why or cwd}")
    return found


def _assert_auto_selection_has_no_structural_not_executed(module, monkeypatch, tmp_path) -> None:
    """상시 잡(문서만 바뀐 변경에서도 고르는 잡)에 구조적 미실행이 0건이다 — 있으면 모든 실행이
    exit 3이다. 깨지면 그 스텝을 해석 가능하게 만들거나(HARN-180 ②처럼) 잡 선택을 다시 본다."""
    names = _auto_selected(module, monkeypatch, tmp_path, ["docs/reviews/x.md"])
    assert len(names) >= 4, f"상시 잡 열거가 비었다 — 스캔 0건은 통과가 아니다: {names}"
    workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    default_shell = mirror._run_defaults(workflow).get("shell")
    offenders = {
        n: _static_not_executed(workflow["jobs"][n], _REPO_ROOT, default_shell) for n in names
    }
    assert {n: v for n, v in offenders.items() if v} == {}


def _assert_old_format_is_unknown(module, tmp_path: Path) -> None:
    """옛 형식은 exit 0이어도 통과로 읽지 않는다 — 미실행 수를 판정할 수 없기 때문이다."""
    path = tmp_path / "r.json"
    _write_old_format_result(path)
    verdict = module.mirror_verdict(path, "a" * 40)
    assert verdict.state == module.VERDICT_UNKNOWN, verdict
    assert "형식" in verdict.reason


#: 원 사고(2026-09-22 webapp 잡 "공개 산출물 검사")와 같은 형태 — 파이프의 마지막이 아닌 grep이
#: no-match에서 exit 1을 낸다. pipefail이 없으면 wc의 0이 그것을 가려 통과하고, 있으면 그
#: 1이 파이프라인 상태가 되어 `set -e`가 스크립트를 판정 전에 죽인다.
_GREP_PIPE_RUN = "leak=$(printf 'abc\\n' | grep zzz | wc -l)\ntest \"$leak\" = 0\n"

#: (워크플로 defaults shell, 잡 defaults shell, 스텝 shell) → 같은 grep 파이프 스텝의 결과.
#: 우선순위는 GitHub와 같다 — 스텝 > 잡 > 워크플로. `pipefail` = FAILED(exit 1) · `loose` =
#: PASSED · `excluded` = 실행하지 않음(NOT_EXECUTED). 빈 문자열과 `sh`는 의도된 제외다: 빈 값도
#: '선언'이며(falsy 판별로 접으면 선언 없음으로 새어 loose가 된다), 미러는 bash 두 형태만 재현한다.
_SHELL_CASES = [
    (None, None, None, "loose"),
    (None, None, "bash", "pipefail"),
    (None, "bash", None, "pipefail"),
    ("bash", None, None, "pipefail"),
    ("pwsh", "bash", None, "pipefail"),  # 잡이 워크플로를 이긴다
    ("pwsh", None, "bash", "pipefail"),  # 스텝이 워크플로를 이긴다
    (None, "pwsh", "bash", "pipefail"),  # 스텝이 잡을 이긴다
    (None, "bash", "pwsh", "excluded"),  # 그 반대 방향도 스텝이 이긴다
    (None, None, "pwsh", "excluded"),
    (None, None, "sh", "excluded"),
    (None, None, "", "excluded"),
]


def _shell_outcome(module, tmp_path: Path, *, workflow=None, job=None, step=None) -> str:
    """같은 grep 파이프 스텝을 세 곳의 `shell` 선언 조합으로 돌려 결과를 한 단어로 돌려준다."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    step_def: dict = {"name": "grep-pipe", "run": _GREP_PIPE_RUN}
    if step is not None:
        step_def["shell"] = step
    extra = {"defaults": {"run": {"shell": job}}} if job is not None else {}
    wf = _wf([step_def], **extra)
    if workflow is not None:
        wf["defaults"] = {"run": {"shell": workflow}}
    result = module.run_job(wf, "demo", tmp_path).steps[0]
    if result.status == module.NOT_EXECUTED:
        return "excluded"
    if result.status == module.PASSED:
        return "loose"
    assert result.status == module.FAILED and result.exit_code == 1, result
    return "pipefail"


def _assert_grep_pipe_matches_github(module, tmp_path: Path) -> None:
    """HARN-162 ⒜⒝ — 같은 스텝이 shell 키 없음에서는 통과하고 `shell: bash`에서는 실패한다."""
    unset = _shell_outcome(module, tmp_path / "unset")
    assert (
        unset == "loose"
    ), f"shell 키 없는 스텝은 GitHub 기본(bash -e · pipefail 없음)처럼 통과해야 한다: {unset}"
    explicit = _shell_outcome(module, tmp_path / "bash", step="bash")
    assert (
        explicit == "pipefail"
    ), f"`shell: bash`는 pipefail이 켜진 형태(-eo pipefail)라 실패해야 한다: {explicit}"


def _assert_real_failure_fails_in_both_shells(module, tmp_path: Path) -> None:
    """HARN-162 ⒞ — 진짜 실패 스텝은 두 형태 모두에서 실패한다(과소 검출 방지 대조군).

    `false` 뒤에 `echo`가 이어지는 스크립트는 `-e`가 꺼져 있으면 마지막 명령의 0으로 통과한다.
    셸을 느슨하게 바꾸다 `-e`까지 잃은 과잉 수정은 ⒜⒝만으로는 통과하므로 이 절이 필요하다.
    """
    for shell in (None, "bash"):
        workdir = tmp_path / f"real-{shell}"
        workdir.mkdir(parents=True, exist_ok=True)
        step: dict = {"name": "real", "run": "echo before\nfalse\necho after"}
        if shell is not None:
            step["shell"] = shell
        result = module.run_job(_wf([step]), "demo", workdir).steps[0]
        assert result.status == module.FAILED and result.exit_code == 1, (shell, result)
        assert "after" not in result.stdout_tail, f"실패 뒤 명령이 계속 돌았다: {shell}"


def _assert_failure_keeps_both_output_tails(module, tmp_path: Path) -> None:
    """HARN-162 ⒟ — 실패 스텝의 stdout 꼬리가 결과 JSON에 실재한다(stderr와 섞이지도 않는다).

    GitHub 형식 오류(`::error::`)는 stdout으로 나온다. 2026-09-22 실측에서 원인이 남지 않은
    상태(stderr 빈 문자열)를 그대로 재현하고, stderr가 함께 있어도 stdout이 사라지지 않는지
    본다. 대조군: 통과 스텝은 stdout을 싣지 않는다(설치 로그가 JSON을 부풀리는 것을 막는다).
    """
    tmp_path.mkdir(parents=True, exist_ok=True)

    def run_one(script: str):
        wf = _wf([{"name": "s", "run": script}])
        return module.run_job(wf, "demo", tmp_path).steps[0]

    only_stdout = run_one('echo "::error::구체적 원인"; exit 3')
    assert only_stdout.exit_code == 3
    assert only_stdout.stderr_tail == "", "stderr가 비어 있는 것이 원 사고 상태다 — 섞으면 안 된다"
    assert "::error::구체적 원인" in only_stdout.stdout_tail
    job = module.JobResult(name="demo", steps=[only_stdout])
    payload = module.build_payload([job], tmp_path, Path("ci.yml"))
    saved_path = tmp_path / "saved.json"
    module.save_payload(payload, saved_path)
    saved = module.load_payload(saved_path)
    assert saved is not None
    assert "::error::구체적 원인" in saved["jobs"][0]["steps"][0]["stdout_tail"]

    both = run_one("echo 표준출력원인; echo 표준에러원인 >&2; exit 4")
    assert "표준출력원인" in both.stdout_tail and "표준에러원인" in both.stderr_tail
    assert "표준출력원인" not in both.stderr_tail

    ok = run_one("echo 소음")
    assert ok.status == module.PASSED and ok.stdout_tail == ""


def _assert_unsupported_shell_is_not_run(module, tmp_path: Path) -> None:
    """HARN-162 — 모르는 셸은 bash로 돌리지 않고 미실행으로 센다(통과로 새지 않는다).

    표식 파일이 생기면 스텝이 실제로 돈 것이다. 대조군: 같은 스크립트가 `shell: bash`에서는
    돈다 — 제외가 모든 스텝을 안 돌리는 과잉 수정이 아님을 보인다.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    wf = _wf(
        [
            {"name": "ok", "run": "true"},
            {"name": "py", "shell": "pwsh", "run": "touch ran.marker"},
        ]
    )
    result = module.run_job(wf, "demo", tmp_path)
    step = result.steps[1]
    assert step.status == module.NOT_EXECUTED, step
    assert "pwsh" in step.reason
    assert not (tmp_path / "ran.marker").exists(), "모르는 셸을 bash로 돌렸다"
    assert module.payload_exit([result]) == 3, "미실행이 통과(exit 0)로 새 나갔다"

    control = tmp_path / "control"
    control.mkdir()
    wf_bash = _wf([{"name": "bash", "shell": "bash", "run": "touch ran.marker"}])
    assert module.run_job(wf_bash, "demo", control).steps[0].status == module.PASSED
    assert (control / "ran.marker").exists()


def _assert_shell_precedence(module, tmp_path: Path) -> None:
    """HARN-162 — 스텝 > 잡 defaults > 워크플로 defaults, 선언의 유무는 `is None`으로 가른다."""
    for index, (wf_shell, job_shell, step_shell, expected) in enumerate(_SHELL_CASES):
        got = _shell_outcome(
            module, tmp_path / f"case-{index}", workflow=wf_shell, job=job_shell, step=step_shell
        )
        assert (
            got == expected
        ), f"워크플로={wf_shell!r} 잡={job_shell!r} 스텝={step_shell!r}: 기대 {expected} · 실제 {got}"


# ── ① 스텝 순차 실행 · skipped 계상 ───────────────────────────────────────
class TestStepSequencing:
    def test_failure_marks_following_steps_as_skipped(self, tmp_path):
        """앞 스텝 실패 → 뒤 스텝은 실행되지 않고 skipped로 계상된다.

        이 절이 없으면 뒤 스텝이 그냥 실행되거나 결과에서 사라진다. 둘 다
        "이번 실행에서 아무것도 모르는 검사"의 수를 말해 주지 못한다.
        """
        wf = _wf(
            [
                {"name": "ok", "run": "true"},
                {"name": "boom", "run": "exit 3"},
                {"name": "after-1", "run": "true"},
                {"name": "after-2", "run": "true"},
            ]
        )
        result = mirror.run_job(wf, "demo", tmp_path)
        by_name = {s.name: s for s in result.steps}
        assert by_name["ok"].status == mirror.PASSED
        assert by_name["boom"].status == mirror.FAILED
        assert by_name["boom"].exit_code == 3
        assert by_name["after-1"].status == mirror.SKIPPED_AFTER_FAILURE
        assert by_name["after-2"].status == mirror.SKIPPED_AFTER_FAILURE
        assert len(result.skipped_after_failure) == 2
        assert result.exit_code == 1

    def test_all_pass_means_zero_skipped(self, tmp_path):
        """대조군 — 전부 통과하면 skipped가 0이어야 한다(모두 skip 처리하는 과잉 수정 방지)."""
        wf = _wf([{"name": "a", "run": "true"}, {"name": "b", "run": "true"}])
        result = mirror.run_job(wf, "demo", tmp_path)
        assert result.exit_code == 0
        assert result.skipped_after_failure == []
        assert len([s for s in result.steps if s.status == mirror.PASSED]) == 2

    def test_timeout_is_recorded_as_failure_with_reason(self, tmp_path):
        """멈춘 사실 자체가 증거다 — 타임아웃은 원인이 남는 실패다."""
        wf = _wf([{"name": "hang", "run": "sleep 30"}])
        result = mirror.run_job(wf, "demo", tmp_path, timeout=1)
        step = result.steps[0]
        assert step.status == mirror.FAILED
        assert "타임아웃" in step.reason

    def test_step_results_flushed_immediately(self, tmp_path):
        """스텝마다 즉시 flush — 중간에 멈춰도 거기까지의 증거가 남는다."""
        log = tmp_path / "steps.ndjson"
        wf = _wf([{"name": "a", "run": "true"}, {"name": "b", "run": "exit 1"}])
        with log.open("w", encoding="utf-8") as handle:
            mirror.run_job(wf, "demo", tmp_path, log_handle=handle)
        lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert [entry["name"] for entry in lines] == ["a", "b"]
        assert lines[1]["exit_code"] == 1

    def test_stderr_tail_preserved_on_failure(self, tmp_path):
        """실패 *원인*이 남는가 — exit code만으로는 8개의 실패가 같은 글자로 보인다."""
        wf = _wf([{"name": "noisy", "run": "echo 구체적원인 >&2; exit 7"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.exit_code == 7
        assert "구체적원인" in step.stderr_tail


# ── ② 실행 불가 스텝은 통과로 계상하지 않는다 ─────────────────────────────
class TestNotRunnable:
    """돌리지 않은 스텝은 통과가 아니다 — 그리고 환경 전제와 미실행은 다른 칸이다(HARN-180).

    액션 스텝만 환경 전제다. 식·조건·작업 디렉터리 때문에 못 돌린 `run` 스텝은 CI에서는 도는
    검사이므로 미실행으로 센다 — 종전에는 둘이 한 칸이라, 건너뛴 검사가 "환경 전제"와 섞여
    판정 줄에서 사라졌다.
    """

    def test_uses_action_is_environment_premise(self, tmp_path):
        wf = _wf([{"name": "checkout", "uses": "actions/checkout@v4"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_RUNNABLE
        assert step.status != mirror.PASSED
        assert "액션" in step.reason

    def test_expression_step_is_not_executed(self, tmp_path):
        """${{ }}를 빈 문자열로 치환해 돌리면 *다른 명령*의 결과를 이 스텝 것으로 보고한다.

        그렇다고 환경 전제로 세면 안 된다 — CI에서는 도는 검사를 이번에 빠뜨린 것이다.
        """
        wf = _wf([{"name": "secret", "run": "echo ${{ secrets.TOKEN }}"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_EXECUTED
        assert "식" in step.reason

    def test_conditional_step_is_not_executed(self, tmp_path):
        wf = _wf([{"name": "cond", "run": "true", "if": "failure()"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_EXECUTED

    def test_missing_working_directory_is_not_executed(self, tmp_path):
        wf = _wf([{"name": "x", "run": "true"}], defaults={"run": {"working-directory": "nope"}})
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_EXECUTED
        assert "작업 디렉터리" in step.reason

    def test_step_without_run_is_not_executed(self, tmp_path):
        """run도 uses도 없는 스텝은 모르는 것이다 — 환경 전제로 접으면 통과 쪽으로 샌다."""
        wf = _wf([{"name": "empty"}])
        assert mirror.run_job(wf, "demo", tmp_path).steps[0].status == mirror.NOT_EXECUTED

    def test_not_run_steps_do_not_fail_the_job(self, tmp_path):
        """실행 불가는 실패가 아니다 — 그렇게 세면 사람이 도구를 끈다."""
        wf = _wf(
            [
                {"name": "a", "uses": "actions/checkout@v4"},
                {"name": "b", "run": "true", "if": "always()"},
                {"name": "c", "run": "true"},
            ]
        )
        result = mirror.run_job(wf, "demo", tmp_path)
        assert result.exit_code == 0
        assert len(result.not_runnable) == 1
        assert len(result.not_executed) == 1


# ── ②-b working-directory의 github.workspace 해석 (HARN-180 ②) ────────────
class TestWorkspaceResolution:
    """`${{ github.workspace }}`만 저장소 루트로 푼다 — 그 밖의 식은 추측하지 않는다."""

    def test_workspace_step_runs_at_repo_root(self, tmp_path):
        """④⑴ — 실제로 돈다. 잡 기본값(src/backend)이 아니라 루트에서 돈다."""
        _assert_workspace_step_runs(mirror, tmp_path)

    def test_workspace_subpath_resolves_under_root(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "here.txt").write_text("x", encoding="utf-8")
        wf = _wf([{"name": "s", "working-directory": f"{_WS}/sub", "run": "test -f here.txt"}])
        assert mirror.run_job(wf, "demo", tmp_path).steps[0].status == mirror.PASSED

    def test_whitespace_variants_are_the_same_expression(self, tmp_path):
        """중괄호 안 공백은 GitHub 문법상 자유다 — 표기 차이로 미실행이 되면 안 된다."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "m.txt").write_text("x", encoding="utf-8")
        for expr in ("${{github.workspace}}", "${{   github.workspace   }}"):
            wf = _wf(
                [{"name": "s", "working-directory": expr, "run": "test -f m.txt"}],
                defaults={"run": {"working-directory": "sub"}},
            )
            step = mirror.run_job(wf, "demo", tmp_path).steps[0]
            assert step.status == mirror.PASSED, f"{expr!r}: {step}"

    def test_job_default_workspace_resolves(self, tmp_path):
        """잡 `defaults.run.working-directory`에 쓴 식도 같은 규칙이다."""
        (tmp_path / "m.txt").write_text("x", encoding="utf-8")
        wf = _wf(
            [{"name": "s", "run": "test -f m.txt"}],
            defaults={"run": {"working-directory": _WS}},
        )
        assert mirror.run_job(wf, "demo", tmp_path).steps[0].status == mirror.PASSED

    def test_other_expression_stays_not_executed(self, tmp_path):
        """④⑵ — `${{ matrix.dir }}`는 풀지 않는다. 비우거나 루트로 대신하면 다른 곳에서 돈
        결과를 이 스텝 것으로 보고하게 된다 — 그래서 실행 흔적 자체가 없어야 한다."""
        wf = _wf([{"name": "m", "working-directory": "${{ matrix.dir }}", "run": "touch ran.txt"}])
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_EXECUTED
        assert "식" in step.reason
        assert not list(tmp_path.rglob("ran.txt")), "해석하지 않는 식인데 어딘가에서 실행됐다"

    def test_partially_resolvable_path_is_not_guessed(self, tmp_path):
        """앞의 github.workspace만 풀고 뒤의 식을 추측하지 않는다."""
        wf = _wf(
            [{"name": "m", "working-directory": _WS + "/${{ matrix.x }}", "run": "touch ran.txt"}]
        )
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.NOT_EXECUTED
        assert not list(tmp_path.rglob("ran.txt"))

    @pytest.mark.skipif(
        sys.platform == "win32", reason="POSIX에서만 역슬래시를 파일 이름에 쓸 수 있다"
    )
    def test_backslash_in_root_path_does_not_break_substitution(self, tmp_path):
        """치환값을 문자열로 넘기면 Windows 경로의 `\\U` 같은 역슬래시가 re 이스케이프로
        해석돼 터진다. POSIX에서 같은 조건(루트 경로 안의 역슬래시)을 재현한다."""
        root = tmp_path / "C:\\Users\\kiki"
        root.mkdir()
        (root / "m.txt").write_text("x", encoding="utf-8")
        wf = _wf([{"name": "s", "working-directory": _WS, "run": "test -f m.txt"}])
        assert mirror.run_job(wf, "demo", root).steps[0].status == mirror.PASSED


# ── ②-c 판정 줄·종료 코드 정직화 (HARN-180 ③) ─────────────────────────────
class TestHonestVerdictLine:
    """미실행이 1건이라도 있으면 최종 줄·종료 코드가 통과라고 말하지 않는다."""

    _PARTIAL = [
        {"name": "ok", "run": "true"},
        {"name": "matrix-gate", "working-directory": "${{ matrix.dir }}", "run": "true"},
    ]

    @pytest.mark.parametrize(
        "step",
        [
            {"name": "cond", "run": "true", "if": "always()"},
            {"name": "expr", "run": "echo ${{ secrets.TOKEN }}"},
            {"name": "wd", "working-directory": "nope", "run": "true"},
            {"name": "mx", "working-directory": "${{ matrix.dir }}", "run": "true"},
        ],
        ids=["조건", "run 안 식", "없는 디렉터리", "해석 불가 식 디렉터리"],
    )
    def test_each_not_run_kind_is_counted(self, tmp_path, step):
        """④⑵ — 못 돌린 검사의 네 원인이 각각 미실행으로 세어지고 판정 줄에 보인다."""
        _assert_not_run_step_is_counted(mirror, tmp_path, step)

    def test_final_line_names_not_executed_count(self, tmp_path):
        result = mirror.run_job(_wf(self._PARTIAL), "demo", tmp_path)
        line = mirror.final_line([result])
        assert "미실행 1건" in line and "demo 1" in line
        assert "전 잡 통과가 아니다" in line
        assert not line.startswith("✔"), "미실행이 있는데 통과 표식으로 시작한다"
        assert mirror.payload_exit([result]) == mirror.EXIT_NOT_EXECUTED == 3

    def test_environment_premise_alone_is_still_a_pass(self, tmp_path):
        """대조군 — 액션 스텝만 못 돌렸으면 통과다. 환경 전제까지 미실행으로 세면 모든 잡이
        영구히 exit 3이 되어 사람이 경고를 끈다(과잉 수정 방지)."""
        wf = _wf(
            [{"name": "checkout", "uses": "actions/checkout@v4"}, {"name": "ok", "run": "true"}]
        )
        result = mirror.run_job(wf, "demo", tmp_path)
        assert mirror.final_line([result]) == "✔ 전 잡 통과"
        assert mirror.payload_exit([result]) == 0

    def test_failure_dominates_and_still_reports_not_executed(self, tmp_path):
        wf = _wf([*self._PARTIAL, {"name": "boom", "run": "exit 4"}])
        result = mirror.run_job(wf, "demo", tmp_path)
        line = mirror.final_line([result])
        assert line.startswith("✗ 실패 잡: demo")
        assert "미실행 1건" in line
        assert mirror.payload_exit([result]) == 1

    def test_render_separates_not_executed_from_premise(self, tmp_path):
        wf = _wf([{"name": "checkout", "uses": "actions/checkout@v4"}, *self._PARTIAL])
        text = mirror.render([mirror.run_job(wf, "demo", tmp_path)])
        assert "(exit 0 · 미실행 1)" in text, "잡 머리말이 '(exit 0)'뿐이면 그 줄이 통과로 읽힌다"
        assert "미실행 1건" in text and "환경 전제 1건" in text

    def test_run_cli_exits_3_with_honest_last_line(self, tmp_path, monkeypatch, capsys):
        """종료 코드로 판정하는 사람에게도 통과로 보이지 않는다 — 2026-09-27 실측의 형태."""
        repo = _init_git_repo(tmp_path / "repo")
        wf_path = repo / "ci.yml"
        wf_path.write_text(yaml.safe_dump(_wf(self._PARTIAL)), encoding="utf-8")
        monkeypatch.chdir(repo)
        # 결과 파일은 저장소 밖에 둔다 — 작업 트리를 흔들지 않는 미러 산출물의 정석 위치다.
        result_path = tmp_path / "r.json"
        rc = mirror.main(
            ["--workflow", str(wf_path), "--result", str(result_path), "run", "--job", "demo"]
        )
        out = capsys.readouterr().out
        assert rc == mirror.EXIT_NOT_EXECUTED
        assert "미실행 1건" in out.strip().splitlines()[-1]
        assert "✔ 전 잡 통과" not in out
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        assert payload["schema"] == mirror.RESULT_SCHEMA
        assert payload["not_executed"] == 1 and payload["exit"] == 3


# ── ③ 사용 오류는 통과가 아니다 ───────────────────────────────────────────
class TestUsageErrors:
    def test_unknown_job_name_raises(self, tmp_path):
        with pytest.raises(mirror.MirrorUsageError):
            mirror.run_job(_wf([{"name": "a", "run": "true"}]), "오타난잡", tmp_path)

    def test_zero_steps_is_failure_not_pass(self, tmp_path):
        with pytest.raises(mirror.MirrorUsageError):
            mirror.run_job(_wf([]), "demo", tmp_path)

    def test_main_returns_two_on_unknown_job(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(_REPO_ROOT)
        rc = mirror.main(
            [
                "--workflow",
                str(_CI_PATH),
                "--result",
                str(tmp_path / "r.json"),
                "run",
                "--job",
                "없는잡",
            ]
        )
        assert rc == 2, "잡 이름 오타는 사용 오류(exit 2)여야 한다"
        assert "없는잡" in capsys.readouterr().err


# ── ④ 출력 억제·절단 스텝도 exit code로 판정 ──────────────────────────────
class TestExitCodeIsTheVerdict:
    def test_quiet_and_tail_do_not_hide_failure(self, tmp_path):
        """2026-08-09 축 재현 — `-q`와 `| tail`이 섞여도 판정은 exit code다.

        파이프 앞단의 실패가 보존되는가는 **스텝의 셸 선언**이 정한다(HARN-162). `shell: bash`는
        pipefail이 켜져 있어 tail의 exit 0이 앞 명령의 실패를 덮지 못한다. 선언 없는 스텝은
        GitHub도 pipefail 없이 돌리므로 이 형태가 CI에서도 가려진다 — 그 대조는
        `TestShellMatchesGitHub`가 맡는다. (종전 이 테스트는 선언 없는 스텝에도 pipefail을 기대해
        미러가 CI보다 엄격하다는 전제를 굳히고 있었다.)
        """
        wf = _wf(
            [
                {
                    "name": "quiet-fail",
                    "shell": "bash",
                    "run": "bash -c 'echo x >&2; exit 5' | tail -1",
                }
            ]
        )
        step = mirror.run_job(wf, "demo", tmp_path).steps[0]
        assert step.status == mirror.FAILED, "파이프가 실패를 삼켰다 — pipefail 미적용"
        assert step.exit_code == 5

    def test_silent_success_is_still_pass(self, tmp_path):
        """대조군 — 조용한 성공은 성공이다."""
        wf = _wf([{"name": "quiet-ok", "run": "true | tail -1"}])
        assert mirror.run_job(wf, "demo", tmp_path).steps[0].status == mirror.PASSED

    def test_shell_flags_match_github_actions(self):
        """`-u`를 더하면 CI보다 엄격해져 거짓 실패를 낸다 — 두 형태의 인자열을 동결한다.

        소스 문자열이 아니라 `step_shell_argv`가 돌려주는 **실제 인자열**을 본다(HARN-162): 종전
        문자열 검사는 pipefail 인자열이 소스에 '있기만 하면' 통과해, 그것이 모든 스텝에
        적용되는 오류를 못 봤다.
        """
        unset, _ = mirror.step_shell_argv({}, {"run": "x"})
        explicit, _ = mirror.step_shell_argv({}, {"shell": "bash", "run": "x"})
        assert unset == ["bash", "-e"]
        assert explicit == ["bash", "--noprofile", "--norc", "-eo", "pipefail"]
        for argv in (unset, explicit):
            assert not any(
                re.fullmatch(r"-[a-z]*u[a-z]*", arg) for arg in argv
            ), f"CI 기본에 없는 -u를 쓰면 거짓 실패가 난다: {argv}"


# ── ④-b 스텝의 셸은 GitHub가 그 스텝에 쓰는 셸이다 (HARN-162) ──────────────
class TestShellMatchesGitHub:
    """미러가 CI보다 엄격하면 거짓 실패가 나고, 느슨하면 진짜 실패를 놓친다 — 양쪽을 다 묶는다.

    실측(2026-09-22): 미러가 모든 스텝을 `bash -eo pipefail`로 돌리며 주석에 "GitHub Actions의
    bash 기본과 정확히 맞춘다"고 적었는데, 그것은 `shell: bash`를 **명시**했을 때의 형태다.
    선언 없는 스텝의 기본은 `bash -e`(pipefail 없음)다. 각 절마다 그 절이 없으면 통과하는 입력을
    픽스처로 둔다 — 아래 뮤테이션(M16~)이 절마다 RED를 확인한다.
    """

    def test_grep_pipe_passes_without_shell_key_and_fails_with_bash(self, tmp_path):
        """⒜⒝ — 원 사고 형태. 선언 없음에서 통과하고 `shell: bash`에서 실패한다."""
        _assert_grep_pipe_matches_github(mirror, tmp_path)

    def test_real_failure_fails_in_both_shells(self, tmp_path):
        """⒞ — 진짜 실패는 두 형태 모두에서 실패한다(셸을 느슨하게 하다 -e를 잃은 과잉 수정 방지)."""
        _assert_real_failure_fails_in_both_shells(mirror, tmp_path)

    def test_failure_keeps_stdout_and_stderr_tails(self, tmp_path):
        """⒟ — stdout 꼬리가 결과 JSON에 실재하고 stderr와 섞이지 않는다."""
        _assert_failure_keeps_both_output_tails(mirror, tmp_path)

    def test_unsupported_shell_is_not_run_as_bash(self, tmp_path):
        """모르는 셸을 bash로 돌리면 그 결과는 그 스텝의 것이 아니다 — 실행하지 않고 미실행으로 센다."""
        _assert_unsupported_shell_is_not_run(mirror, tmp_path)

    def test_shell_precedence_is_step_then_job_then_workflow(self, tmp_path):
        _assert_shell_precedence(mirror, tmp_path)

    def test_run_step_direct_call_keeps_default_shell_optional(self, tmp_path):
        """`default_shell`은 뒤에 붙인 선택 인자다 — 기존 호출 형태가 그대로 돈다."""
        step = {"name": "s", "run": "true"}
        result = mirror.run_step({"steps": [step]}, step, tmp_path, 30)
        assert result.status == mirror.PASSED


# ── ⑤ 결과 JSON · done 프리플라이트 ───────────────────────────────────────
class TestVerdict:
    def test_missing_result_is_unknown_not_pass(self, tmp_path):
        ok, reason = mirror.verdict_for_commit(tmp_path / "absent.json", "abc123")
        assert ok is False
        assert "없음" in reason

    def test_commit_mismatch_is_reported(self, tmp_path):
        path = tmp_path / "r.json"
        _write_result(path, [_job("backend", ("pytest", mirror.PASSED))], commit="0" * 40)
        ok, reason = mirror.verdict_for_commit(path, "f" * 40)
        assert ok is False
        assert "다른 커밋" in reason, "커밋 불일치를 '통과'로 접으면 이전 실행의 증거를 재사용한다"

    def test_failed_run_is_not_pass(self, tmp_path):
        path = tmp_path / "r.json"
        _write_result(path, [_job("backend", ("pytest", mirror.FAILED))], commit="a" * 40)
        ok, reason = mirror.verdict_for_commit(path, "a" * 40)
        assert ok is False and "backend" in reason
        assert mirror.mirror_verdict(path, "a" * 40).state == mirror.VERDICT_FAIL

    def test_top_level_failure_code_is_not_overridden_by_job_rows(self, tmp_path):
        """최상위 exit가 실패인데 잡 행이 전부 0인 모순 결과 — 잡 행만 믿고 통과로 읽지 않는다."""
        path = tmp_path / "r.json"
        payload = _write_result(path, [_job("j", ("ok", mirror.PASSED))], commit="a" * 40)
        payload["exit"] = 1
        mirror.save_payload(payload, path)
        assert mirror.mirror_verdict(path, "a" * 40).state == mirror.VERDICT_FAIL

    def test_matching_commit_and_zero_exit_passes(self, tmp_path):
        """대조군 — 환경 전제(액션 스텝)만 있는 결과는 통과다."""
        path = tmp_path / "r.json"
        _write_result(
            path,
            [_job("infra-shell", ("checkout", mirror.NOT_RUNNABLE), ("ok", mirror.PASSED))],
            commit="a" * 40,
        )
        ok, reason = mirror.verdict_for_commit(path, "a" * 40)
        assert ok is True and "infra-shell" in reason

    def test_not_executed_is_not_pass_and_is_named(self, tmp_path):
        """④⑵ — 미실행이 있으면 verdict는 통과가 아니고, 그 수와 스텝 이름을 말한다."""
        path = tmp_path / "r.json"
        _write_result(
            path,
            [
                _job(
                    "declared-unwired-audit",
                    ("정적 감사", mirror.PASSED),
                    ("게이트 — OPS-24", mirror.NOT_EXECUTED),
                )
            ],
            commit="a" * 40,
        )
        verdict = mirror.mirror_verdict(path, "a" * 40)
        assert verdict.state == mirror.VERDICT_NOT_EXECUTED
        assert verdict.exit_code == mirror.EXIT_NOT_EXECUTED
        assert "미실행 1건" in verdict.reason
        assert "declared-unwired-audit › 게이트 — OPS-24" in verdict.reason
        ok, _ = mirror.verdict_for_commit(path, "a" * 40)
        assert ok is False, "bool 창구가 미실행을 통과로 접었다 — done 경고가 그것을 통과로 읽는다"

    def test_long_not_executed_list_is_truncated_but_counted(self, tmp_path):
        path = tmp_path / "r.json"
        steps = [(f"스텝{i}", mirror.NOT_EXECUTED) for i in range(12)]
        _write_result(path, [_job("j", *steps)], commit="a" * 40)
        reason = mirror.mirror_verdict(path, "a" * 40).reason
        assert "미실행 12건" in reason and "외 4건" in reason

    def test_old_format_result_is_unknown(self, tmp_path):
        """옛 형식은 건너뛴 검사를 환경 전제 칸(not_runnable)에 넣었다 — exit 0이어도 통과로
        읽지 않는다. 픽스처가 2026-09-27 실측 결과의 형태 그대로다(schema 없음)."""
        _assert_old_format_is_unknown(mirror, tmp_path)

    def test_verdict_contract_helper(self, tmp_path):
        """뮤테이션 M12가 쓰는 단언의 원본 대조 — 원본 모듈에서는 GREEN이어야 한다."""
        _assert_verdict_names_not_executed(mirror, tmp_path)

    def test_zero_jobs_is_unknown(self, tmp_path):
        """스캔 0건은 통과가 아니다 — 잡 0건 결과를 "통과 — 잡 0건"으로 말하지 않는다."""
        path = tmp_path / "r.json"
        payload = {"schema": mirror.RESULT_SCHEMA, "commit": "a" * 40, "exit": 0, "jobs": []}
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert mirror.mirror_verdict(path, "a" * 40).state == mirror.VERDICT_UNKNOWN

    @pytest.mark.parametrize(
        "jobs",
        [5, {"j": 1}, [{"name": "j", "exit": 0}], [{"name": "j", "exit": 0, "steps": 3}]],
        ids=["int", "dict", "steps-missing", "steps-int"],
    )
    def test_malformed_result_is_unknown_not_crash(self, tmp_path, jobs):
        """손상된 결과로 done 프리플라이트가 예외를 내며 죽으면 판정 대신 크래시가 남는다.
        스텝 기록이 빠진 잡을 "미실행 0건"으로 읽는 것도 모르는 것을 아니라고 접는 것이다."""
        path = tmp_path / "r.json"
        payload = {"schema": mirror.RESULT_SCHEMA, "commit": "a" * 40, "exit": 0, "jobs": jobs}
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert mirror.mirror_verdict(path, "a" * 40).state == mirror.VERDICT_UNKNOWN

    def test_corrupt_json_is_unknown_not_crash(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text("{깨진", encoding="utf-8")
        ok, _ = mirror.verdict_for_commit(path, "a" * 40)
        assert ok is False

    def test_verdict_cli_exit_codes(self, tmp_path, monkeypatch, capsys):
        """verdict 종료 코드 — 0 통과 · 3 미실행 · 1 실패·결과 없음. 문장만 바꾸고 코드를
        0으로 두면 exit code로 판정하는 쪽에는 여전히 통과로 보인다."""
        monkeypatch.setattr(mirror, "current_commit", lambda root: "c" * 40)
        path = tmp_path / "r.json"
        cases = [
            ([_job("j", ("ok", mirror.PASSED))], 0),
            ([_job("j", ("ok", mirror.PASSED), ("m", mirror.NOT_EXECUTED))], 3),
            ([_job("j", ("boom", mirror.FAILED))], 1),
        ]
        for jobs, expected in cases:
            _write_result(path, jobs)
            assert mirror.main(["--result", str(path), "verdict"]) == expected
        path.unlink()
        assert mirror.main(["--result", str(path), "verdict"]) == 1
        assert "미실행 1건" in capsys.readouterr().out


# ── ⑥ 배선 실재 — 정본화와 집행 지점의 분리 ───────────────────────────────
class TestWiring:
    def test_drive_runbook_calls_the_mirror(self):
        """정본화 축 — 런북이 미러를 부르는가(존재만으로는 배선이 아니다)."""
        text = _DRIVE_DOC.read_text(encoding="utf-8")
        assert "ci_mirror.py run" in text
        assert (
            "pytest` (+해당 시 `flutter test`) · `ruff` green" not in text
        ), "종전 문구가 남아 있으면 사람이 그쪽을 읽는다"

    def test_done_command_calls_preflight(self):
        """집행 지점 축 — done이 실제로 프리플라이트를 호출하는가."""
        source = _BACKLOG_CLI.read_text(encoding="utf-8")
        assert "def _warn_if_ci_mirror_missing" in source
        done_body = source.split("def cmd_done(", 1)[1].split("\ndef ", 1)[0]
        assert (
            "_warn_if_ci_mirror_missing(root)" in done_body
        ), "헬퍼를 정의만 하고 호출하지 않으면 정본화를 집행으로 착각한 것이다"

    def test_preflight_failure_does_not_block_done(self):
        """1단계는 warn이다 — 거부로 바뀌면 이 단언이 깨져 의도적 승격임을 드러낸다."""
        source = _BACKLOG_CLI.read_text(encoding="utf-8")
        helper = source.split("def _warn_if_ci_mirror_missing(", 1)[1].split("\ndef ", 1)[0]
        assert "_fail(" not in helper
        assert "return" in helper


def _done_warning(module, tmp_path: Path, monkeypatch, capsys, jobs: list) -> str:
    """done 프리플라이트(`_warn_if_ci_mirror_missing`)를 실제로 불러 stderr를 돌려준다."""
    _write_result(tmp_path / mirror.DEFAULT_RESULT_PATH, jobs)
    monkeypatch.setattr(mirror, "current_commit", lambda root: "c" * 40)
    module._warn_if_ci_mirror_missing(tmp_path)
    return capsys.readouterr().err


def _assert_done_warns_not_executed_as_not_run(module, tmp_path, monkeypatch, capsys) -> None:
    """HARN-180 ③ done 축 — 미실행을 통과로도, "다시 돌려라"로도 안내하지 않는다.

    다시 돌려도 같은 스텝은 또 돌지 않으므로 재현 처방은 틀린 안내다. 뮤테이션 테스트가 같은
    함수를 변이 backlog 모듈에 대고 RED를 확인한다.
    """
    jobs = [
        _job(
            "declared-unwired-audit",
            ("정적 감사", mirror.PASSED),
            ("게이트 — OPS-24", mirror.NOT_EXECUTED),
        )
    ]
    err = _done_warning(module, tmp_path, monkeypatch, capsys, jobs)
    assert "미실행 1건" in err and "게이트 — OPS-24" in err
    assert "돌지 않은 검사" in err
    assert "재현한 뒤" not in err, "미실행에 재현 처방을 내면 같은 스텝이 또 안 돈다"


class TestDonePreflightBehavior:
    """집행 지점의 *동작* — TestWiring은 호출 여부만 소스로 본다(HARN-180 ③)."""

    @pytest.fixture
    def backlog_cli(self, monkeypatch):
        monkeypatch.setattr(sys, "path", [str(_BACKLOG_CLI.parent), *sys.path])
        import backlog  # noqa: PLC0415  (scripts/harness 단독 실행 모듈)

        return backlog

    def test_not_executed_is_warned_as_not_run(self, backlog_cli, tmp_path, monkeypatch, capsys):
        _assert_done_warns_not_executed_as_not_run(backlog_cli, tmp_path, monkeypatch, capsys)

    def test_pass_is_silent(self, backlog_cli, tmp_path, monkeypatch, capsys):
        """대조군 — 통과면 아무 말도 하지 않는다(모든 done에 경고가 붙으면 습관화된다)."""
        jobs = [_job("j", ("checkout", mirror.NOT_RUNNABLE), ("ok", mirror.PASSED))]
        assert _done_warning(backlog_cli, tmp_path, monkeypatch, capsys, jobs) == ""

    def test_failure_keeps_rerun_advice(self, backlog_cli, tmp_path, monkeypatch, capsys):
        jobs = [_job("backend", ("pytest", mirror.FAILED))]
        err = _done_warning(backlog_cli, tmp_path, monkeypatch, capsys, jobs)
        assert "실패" in err and "재현한 뒤" in err


# ── ⑦ 뮤테이션 — 도구를 깨뜨리면 테스트가 RED인가 ─────────────────────────
class TestMutationSelfCheck:
    """실행 파일을 건드리지 않고, 동일 로직을 깨뜨린 사본으로 변별력을 확인한다."""

    _counter = 0

    @classmethod
    def _mutated_module(cls, tmp_path: Path, old: str, new: str, source: Path = _MIRROR_PATH):
        original = source.read_text(encoding="utf-8")
        assert original.count(old) == 1, f"치환 대상이 1건이 아니다: {old[:50]!r}"
        mutated = original.replace(old, new, 1)
        assert mutated != original, "주입이 적용되지 않았다 — 하네스 결함"
        cls._counter += 1
        name = f"{source.stem}_mutant_{cls._counter}"
        target = tmp_path / f"{name}.py"
        target.write_text(mutated, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(name, target)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        # exec_module *전에* 등록해야 한다 — dataclass가 sys.modules[cls.__module__]를
        # 조회하므로 미등록 상태로 실행하면 AttributeError로 죽는다(하네스 결함이
        # 뮤테이션 결과를 가리는 형태).
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)
        return module, original

    def test_m1_skipping_not_counted_is_detected(self, tmp_path):
        """M1: 실패 후 뒤 스텝을 그냥 실행하면 skipped 계상이 0이 된다."""
        mutant, original = self._mutated_module(
            tmp_path, "        if failed:\n", "        if False:\n"
        )
        wf = _wf([{"name": "boom", "run": "exit 1"}, {"name": "after", "run": "true"}])
        result = mutant.run_job(wf, "demo", tmp_path)
        assert len(result.skipped_after_failure) == 0, "뮤테이션이 적용되지 않았다"
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    def test_m2_unknown_job_silently_passing_is_detected(self, tmp_path):
        """M2: 잡 이름 오타를 거부하지 않으면 빈 결과가 '통과'로 보인다."""
        mutant, original = self._mutated_module(
            tmp_path,
            '        raise MirrorUsageError(f"ci.yml에 없는 잡 이름: {job_name}")',
            "        return JobResult(name=job_name)",
        )
        result = mutant.run_job(_wf([{"name": "a", "run": "true"}]), "오타", tmp_path)
        assert result.exit_code == 0 and result.steps == [], "뮤테이션이 적용되지 않았다"
        with pytest.raises(mirror.MirrorUsageError):
            mirror.run_job(_wf([{"name": "a", "run": "true"}]), "오타", tmp_path)
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    def test_m3_dropping_pipefail_hides_failure(self, tmp_path):
        """M3: `shell: bash`에서 pipefail을 빼면 `| tail`이 앞 명령의 실패를 삼킨다(2026-08-09 축).

        HARN-162 이후 pipefail은 `shell: bash` 명시 스텝의 몫이라 그 스텝으로 겨냥한다.
        """
        mutant, original = self._mutated_module(
            tmp_path,
            self._BASH,
            '_SHELL_ARGV_BASH = ["bash", "--noprofile", "--norc", "-e"]\n',
        )
        wf = _wf([{"name": "quiet-fail", "shell": "bash", "run": "bash -c 'exit 5' | tail -1"}])
        assert (
            mutant.run_job(wf, "demo", tmp_path).steps[0].status == mutant.PASSED
        ), "뮤테이션이 적용되지 않았다 — pipefail 제거가 반영되어야 한다"
        assert mirror.run_job(wf, "demo", tmp_path).steps[0].status == mirror.FAILED
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    def test_mutations_leave_source_byte_identical(self, tmp_path):
        digest = hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest()
        self._mutated_module(tmp_path, 'PASSED = "passed"', 'PASSED = "PASSED"')
        assert hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest() == digest

    # ── HARN-180 — 해석·분류·판정 절마다: 그 절을 지우면 계약 단언이 RED인가 ──────
    # 각 변이 모듈에 *계약 테스트가 쓰는 것과 같은 단언 함수*를 대고 AssertionError를
    # 확인한다(대조군은 원본 모듈로 GREEN). "행동이 달라졌다"가 아니라 "테스트가 잡는다"를
    # 직접 보이는 형태다.
    def test_m4_removing_workspace_resolution_turns_1_red(self, tmp_path):
        """M4 (acceptance ④ 필수): 해석을 지우면 ⑴이 RED — 스텝이 다시 건너뛰어진다."""
        digest = hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest()
        mutant, _ = self._mutated_module(
            tmp_path,
            "    resolved = _WORKSPACE_EXPR_RE.sub(lambda _match: root_text, wd)\n",
            "    resolved = wd\n",
        )
        with pytest.raises(AssertionError):
            _assert_workspace_step_runs(mutant, tmp_path / "mutant")
        _assert_workspace_step_runs(mirror, tmp_path / "control")
        assert hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest() == digest

    def test_m5_falling_back_to_job_default_turns_1_red(self, tmp_path):
        """M5: 식 오버라이드를 무시하고 잡 기본값(src/backend)에서 돌리면 ⑴이 RED.

        2026-09-27 실측에서 OPS-24 게이트가 src/backend에서 FileNotFoundError로 죽은 형태다 —
        ⑴의 픽스처가 "루트에만 있는 표식"으로 이 절을 실제로 밟는지 확인한다.
        """
        mutant, original = self._mutated_module(
            tmp_path,
            '    if isinstance(step.get("working-directory"), str):\n',
            '    if isinstance(step.get("working-directory"), str) and "${{" not in '
            'step["working-directory"]:\n',
        )
        with pytest.raises(AssertionError):
            _assert_workspace_step_runs(mutant, tmp_path / "mutant")
        _assert_workspace_step_runs(mirror, tmp_path / "control")
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    @pytest.mark.skipif(
        sys.platform == "win32", reason="POSIX에서만 역슬래시를 파일 이름에 쓸 수 있다"
    )
    def test_m6_string_replacement_breaks_on_backslash_root(self, tmp_path):
        """M6: 치환값을 함수 대신 문자열로 넘기면 역슬래시 경로에서 re.error로 죽는다."""
        mutant, original = self._mutated_module(
            tmp_path,
            "_WORKSPACE_EXPR_RE.sub(lambda _match: root_text, wd)",
            "_WORKSPACE_EXPR_RE.sub(root_text, wd)",
        )
        root = tmp_path / "C:\\Users\\kiki"
        root.mkdir()
        (root / "m.txt").write_text("x", encoding="utf-8")
        wf = _wf([{"name": "s", "working-directory": _WS, "run": "test -f m.txt"}])
        with pytest.raises(re.error):
            mutant.run_job(wf, "demo", root)
        assert mirror.run_job(wf, "demo", root).steps[0].status == mirror.PASSED
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    @pytest.mark.parametrize(
        ("label", "old", "new", "step"),
        [
            (
                "M7-식·조건을 환경 전제로 접음(원래 결함 형태)",
                '    if isinstance(step, dict) and step.get("uses"):\n'
                "        return NOT_RUNNABLE\n    return NOT_EXECUTED\n",
                "    return NOT_RUNNABLE\n",
                {"name": "cond", "run": "true", "if": "always()"},
            ),
            (
                "M8-없는 작업 디렉터리를 환경 전제로 접음",
                'status=NOT_EXECUTED, reason=f"작업 디렉터리 없음: {cwd}")',
                'status=NOT_RUNNABLE, reason=f"작업 디렉터리 없음: {cwd}")',
                {"name": "wd", "working-directory": "nope", "run": "true"},
            ),
            (
                "M9-해석 불가 식 작업 디렉터리를 환경 전제로 접음",
                "status=NOT_EXECUTED, reason=wd_reason)",
                "status=NOT_RUNNABLE, reason=wd_reason)",
                {"name": "mx", "working-directory": "${{ matrix.dir }}", "run": "true"},
            ),
            (
                "M10-종료 코드가 미실행을 무시",
                "    if any(j.not_executed for j in jobs):\n        return EXIT_NOT_EXECUTED\n",
                "",
                {"name": "mx", "working-directory": "${{ matrix.dir }}", "run": "true"},
            ),
            (
                "M11-최종 줄이 미실행을 통과로 표기",
                "    if count:\n        return (\n",
                "    if False:\n        return (\n",
                {"name": "mx", "working-directory": "${{ matrix.dir }}", "run": "true"},
            ),
        ],
        ids=["M7", "M8", "M9", "M10", "M11"],
    )
    def test_m7_to_m11_not_executed_counting(self, tmp_path, label, old, new, step):
        """M7~M11: 미실행 분류·종료 코드·최종 줄 중 한 절을 지우면 ④⑵ 단언이 RED."""
        mutant, original = self._mutated_module(tmp_path, old, new)
        with pytest.raises(AssertionError):
            _assert_not_run_step_is_counted(mutant, tmp_path / "mutant", step)
        _assert_not_run_step_is_counted(mirror, tmp_path / "control", step)
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original, label

    @pytest.mark.parametrize(
        ("old", "new", "check"),
        [
            (
                "    if not_executed:\n        shown = not_executed[:_LISTED_NOT_EXECUTED]\n",
                "    if False:\n        shown = not_executed[:_LISTED_NOT_EXECUTED]\n",
                "named",
            ),
            (
                '    if payload.get("schema") != RESULT_SCHEMA:\n',
                "    if False:\n",
                "old_format",
            ),
        ],
        # M12 = verdict가 미실행을 통과로 접음 · M13 = 옛 형식 결과를 판정에 씀
        ids=["M12", "M13"],
    )
    def test_m12_m13_verdict(self, tmp_path, old, new, check):
        """M12: verdict가 미실행을 통과로 접으면 RED · M13: 형식 판 검사를 지우면 2026-09-27
        실측 형태의 옛 결과(건너뛴 검사가 환경 전제 칸)가 통과로 읽혀 RED."""
        assert_fn = {
            "named": _assert_verdict_names_not_executed,
            "old_format": _assert_old_format_is_unknown,
        }[check]
        mutant, original = self._mutated_module(tmp_path, old, new)
        (tmp_path / "mutant").mkdir()
        (tmp_path / "control").mkdir()
        with pytest.raises(AssertionError):
            assert_fn(mutant, tmp_path / "mutant")
        assert_fn(mirror, tmp_path / "control")
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    def test_m15_running_filter_job_makes_every_run_exit_3(self, tmp_path, monkeypatch):
        """M15: 경로 필터 잡 제외를 지우면 상시 잡에 구조적 미실행이 생겨 RED(상시 exit 3)."""
        mutant, original = self._mutated_module(
            tmp_path, "    if coverage.FILTER_JOB in runnable:\n", "    if False:\n"
        )
        with pytest.raises(AssertionError):
            _assert_auto_selection_has_no_structural_not_executed(mutant, monkeypatch, tmp_path)
        _assert_auto_selection_has_no_structural_not_executed(mirror, monkeypatch, tmp_path)
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original

    def test_m14_done_folding_not_executed_into_rerun_advice(self, tmp_path, monkeypatch, capsys):
        """M14: done 프리플라이트의 미실행 분기를 지우면 done 축 단언이 RED(backlog.py 변이)."""
        monkeypatch.setattr(sys, "path", [str(_BACKLOG_CLI.parent), *sys.path])
        digest = hashlib.sha256(_BACKLOG_CLI.read_bytes()).hexdigest()
        mutant, _ = self._mutated_module(
            tmp_path,
            "    if verdict.state == ci_mirror.VERDICT_NOT_EXECUTED:\n",
            "    if False:\n",
            source=_BACKLOG_CLI,
        )
        (tmp_path / "mutant").mkdir()
        (tmp_path / "control").mkdir()
        with pytest.raises(AssertionError):
            _assert_done_warns_not_executed_as_not_run(
                mutant, tmp_path / "mutant", monkeypatch, capsys
            )
        import backlog  # noqa: PLC0415

        _assert_done_warns_not_executed_as_not_run(
            backlog, tmp_path / "control", monkeypatch, capsys
        )
        assert hashlib.sha256(_BACKLOG_CLI.read_bytes()).hexdigest() == digest

    # ── HARN-162 — 셸 선택·출력 보존 절마다: 그 절을 깨뜨리면 그 절을 밟는 단언이 RED인가 ──
    _UNSET = '_SHELL_ARGV_UNSET = ["bash", "-e"]\n'
    _BASH = '_SHELL_ARGV_BASH = ["bash", "--noprofile", "--norc", "-eo", "pipefail"]\n'

    @pytest.mark.parametrize(
        ("label", "old", "new", "assert_fn"),
        [
            (
                "M16-선언 없는 스텝에도 pipefail(원래 결함 형태)",
                _UNSET,
                '_SHELL_ARGV_UNSET = ["bash", "--noprofile", "--norc", "-eo", "pipefail"]\n',
                _assert_grep_pipe_matches_github,
            ),
            (
                "M17-`shell: bash`에서 pipefail이 빠짐",
                _BASH,
                '_SHELL_ARGV_BASH = ["bash", "-e"]\n',
                _assert_grep_pipe_matches_github,
            ),
            (
                "M18-선언 없는 기본이 -e를 잃음(과잉 완화)",
                _UNSET,
                '_SHELL_ARGV_UNSET = ["bash"]\n',
                _assert_real_failure_fails_in_both_shells,
            ),
            (
                "M19-`shell: bash`가 -e를 잃음",
                _BASH,
                '_SHELL_ARGV_BASH = ["bash", "--noprofile", "--norc", "-o", "pipefail"]\n',
                _assert_real_failure_fails_in_both_shells,
            ),
            (
                "M20-모르는 셸을 bash로 돌림",
                '    if declared == "bash":\n        return list(_SHELL_ARGV_BASH), ""\n',
                '    if True:\n        return list(_SHELL_ARGV_BASH), ""\n',
                _assert_unsupported_shell_is_not_run,
            ),
            (
                "M21-모르는 셸을 환경 전제로 접음(미실행이 아님)",
                "        return StepResult(name=name, status=NOT_EXECUTED, reason=shell_reason)\n",
                "        return StepResult(name=name, status=NOT_RUNNABLE, reason=shell_reason)\n",
                _assert_unsupported_shell_is_not_run,
            ),
            (
                "M22-잡 defaults의 shell을 무시",
                '        declared = _run_defaults(job).get("shell")\n',
                "        declared = None\n",
                _assert_shell_precedence,
            ),
            (
                "M23-워크플로 defaults의 shell을 무시",
                '    default_shell = _run_defaults(workflow).get("shell")\n',
                "    default_shell = None\n",
                _assert_shell_precedence,
            ),
            (
                "M24-선언 유무를 falsy로 판별(빈 문자열이 선언 없음으로 샘)",
                '    if declared is None:\n        declared = _run_defaults(job).get("shell")\n',
                '    if not declared:\n        declared = _run_defaults(job).get("shell")\n',
                _assert_shell_precedence,
            ),
            (
                "M25-잡 선언이 스텝 선언을 이김(우선순위 역전)",
                '    declared = step.get("shell")\n    if declared is None:\n'
                '        declared = _run_defaults(job).get("shell")\n',
                '    declared = _run_defaults(job).get("shell")\n    if declared is None:\n'
                '        declared = step.get("shell")\n',
                _assert_shell_precedence,
            ),
            (
                "M26-stdout 꼬리를 버림(원래 결함 형태)",
                '        stdout_tail=stdout if code != 0 else "",\n',
                '        stdout_tail="",\n',
                _assert_failure_keeps_both_output_tails,
            ),
            (
                "M27-통과 스텝의 stdout까지 싣음",
                '        stdout_tail=stdout if code != 0 else "",\n',
                "        stdout_tail=stdout,\n",
                _assert_failure_keeps_both_output_tails,
            ),
            (
                "M28-stdout을 stderr 칸에 합침(종전 형태)",
                "        stderr_tail=stderr,\n",
                "        stderr_tail=(stderr or stdout),\n",
                _assert_failure_keeps_both_output_tails,
            ),
        ],
        ids=[f"M{n}" for n in range(16, 29)],
    )
    def test_m16_to_m28_shell_selection_and_output_tails(
        self, tmp_path, label, old, new, assert_fn
    ):
        """M16~M28: 셸 선택·우선순위·출력 보존 중 한 절을 깨뜨리면 그 절의 단언이 RED, 원본은 GREEN."""
        mutant, original = self._mutated_module(tmp_path, old, new)
        with pytest.raises(AssertionError):
            assert_fn(mutant, tmp_path / "mutant")
        assert_fn(mirror, tmp_path / "control")
        assert _MIRROR_PATH.read_text(encoding="utf-8") == original, label


# ── ⑧ 실제 ci.yml 연동 ────────────────────────────────────────────────────
class TestAgainstRealWorkflow:
    def test_auto_job_selection_uses_coverage_tool(self, monkeypatch, tmp_path):
        """--job 미지정이면 HARN-109 열거기가 대상을 계산한다(계약 계승)."""
        monkeypatch.chdir(_REPO_ROOT)
        workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        args = mirror.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "--result", str(tmp_path / "r.json"), "run"]
        )
        monkeypatch.setattr(
            mirror.coverage, "changed_files_from_git", lambda base, root: ["docs/reviews/x.md"]
        )
        names = mirror._resolve_jobs(args, workflow, _REPO_ROOT)
        assert "harness-integrity" in names and "policy-guard" in names
        assert "backend" not in names, "문서 변경인데 backend를 대상으로 골랐다"

    def test_irreproducible_jobs_excluded_from_auto(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(_REPO_ROOT)
        workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        args = mirror.build_parser().parse_args(
            ["--workflow", str(_CI_PATH), "--result", str(tmp_path / "r.json"), "run"]
        )
        monkeypatch.setattr(
            mirror.coverage,
            "changed_files_from_git",
            lambda base, root: ["src/backend/whymath_backend/l3/router.py"],
        )
        names = mirror._resolve_jobs(args, workflow, _REPO_ROOT)
        assert "docker-build" not in names
        assert "재현 불가" in capsys.readouterr().out, "제외 사실을 침묵하면 사람이 통과로 읽는다"

    def test_filter_job_is_replaced_not_run_in_auto(self, monkeypatch, tmp_path, capsys):
        """경로 필터 잡(changes)은 미러의 잡 선택이 대신한다 — 자동 선택에서 사유와 함께 빠진다.

        돌리면 그 filter 스텝(GitHub 식)이 매번 미실행이 되어 자동 선택 실행이 전부 exit 3이
        된다(HARN-180 착지 중 실측 — 첫 미러 실행이 changes를 골랐다).
        """
        names = _auto_selected(mirror, monkeypatch, tmp_path, ["docs/reviews/x.md"])
        assert mirror.coverage.FILTER_JOB not in names
        out = capsys.readouterr().out
        assert (
            f"{mirror.coverage.FILTER_JOB} 잡은 미러 대상에서 제외" in out
        ), "제외를 침묵하면 빠뜨림과 구분되지 않는다"

    def test_always_on_jobs_have_no_structural_not_executed(self, monkeypatch, tmp_path):
        """매 실행에 들어가는 잡에 원리상 못 도는 run 스텝이 있으면 모든 미러 실행이 exit 3이
        되어 경고가 상시 소음이 된다 — 문서만 바뀐 변경의 자동 선택에서 0건이어야 한다."""
        _assert_auto_selection_has_no_structural_not_executed(mirror, monkeypatch, tmp_path)

    def test_workspace_working_directories_resolve_to_real_dirs(self):
        """HARN-180 ①의 실물 대조 — 2026-09-27에 건너뛰어진 OPS-24 게이트 2개가 이제 저장소
        루트로 풀린다. ci.yml 전체에서 github.workspace만 쓰는 working-directory를 전수로 본다
        (스캔 0건은 통과가 아니므로 최소 건수를 단언한다)."""
        workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        resolved: list[tuple[str, str, Path]] = []
        for job_name, job in workflow["jobs"].items():
            for step in job.get("steps") or []:
                wd = str(step.get("working-directory", ""))
                if "github.workspace" not in wd:
                    continue
                cwd, why = mirror.step_working_directory(job, step, _REPO_ROOT)
                assert cwd is not None, f"{job_name} › {step.get('name')}: {why}"
                assert cwd.is_dir(), f"{job_name} › {step.get('name')}: 실재하지 않는 {cwd}"
                resolved.append((job_name, str(step.get("name")), cwd))
        ops24 = [r for r in resolved if r[0] == "declared-unwired-audit" and "OPS-24" in r[1]]
        assert (
            len(ops24) == 2
        ), f"OPS-24 게이트 2개가 대조에서 빠졌다 — 전제를 다시 보라: {resolved}"
        assert all(cwd.resolve() == _REPO_ROOT.resolve() for _, _, cwd in ops24)

    def test_blocking_actions_are_infrastructure_only(self):
        """액션 스텝을 "환경 전제"로 세는 분류(HARN-180 ③)의 전제를 동결한다.

        미러는 액션 스텝을 돌리지 않고 미실행으로도 세지 않는다. 그것이 정직하려면 CI를
        막을 수 있는(continue-on-error 없는) 액션이 준비·보관용뿐이어야 한다. 검사 액션이
        차단형으로 들어오면 미러가 그 검사를 환경 전제 칸에 숨긴다 — 이 테스트가 먼저 RED가
        되어 분류를 다시 보게 한다(2026-09-27 실측: 검사 액션은 비차단 shellcheck 1건뿐).
        """
        workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        scanned = sum(
            1 for job in workflow["jobs"].values() for s in job.get("steps") or [] if s.get("uses")
        )
        assert scanned > 0, "액션 스텝 0건 — 스캔 0건은 통과가 아니다"
        assert _blocking_non_infra_actions(workflow) == [], (
            "차단형 검사 액션이 생겼다 — ci_mirror는 이것을 환경 전제로 숨긴다. 미러 분류를 갱신하거나 "
            "이 목록(_INFRA_ACTIONS)에 준비용임을 근거와 함께 추가하라"
        )

    def test_blocking_check_action_is_flagged(self):
        """위 동결의 변별력 — 차단형 검사 액션은 잡히고, 비차단·준비용은 잡히지 않는다."""
        steps = [
            {"name": "lint", "uses": "some/lint-action@v1"},
            {
                "name": "advisory",
                "uses": "ludeeus/action-shellcheck@master",
                "continue-on-error": True,
            },
            {"name": "Checkout", "uses": "actions/checkout@v4"},
        ]
        assert _blocking_non_infra_actions({"jobs": {"j": {"steps": steps}}}) == ["j › lint"]

    def test_every_run_step_resolves_to_a_shell_the_mirror_reproduces(self):
        """HARN-162 — 실제 ci.yml의 모든 run 스텝이 미러가 재현하는 셸로 풀린다.

        `shell:` 선언이 없는 스텝은 `bash -e`(pipefail 없음)로 풀려야 한다. ci.yml에 미러가 모르는
        셸(`pwsh`·`python` 등)이 들어오면 그 스텝은 조용히 미실행이 되므로, 이 테스트가 먼저 RED가
        되어 미러 분류를 다시 보게 한다. 스캔 0건은 통과가 아니므로 최소 건수를 단언한다.
        """
        workflow = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        default_shell = mirror._run_defaults(workflow).get("shell")
        scanned = 0
        unresolved: list[str] = []
        for job_name, job in workflow["jobs"].items():
            for step in job.get("steps") or []:
                if not isinstance(step.get("run"), str):
                    continue
                scanned += 1
                argv, why = mirror.step_shell_argv(job, step, default_shell)
                if argv is None:
                    unresolved.append(f"{job_name} › {step.get('name')}: {why}")
        assert scanned >= 50, f"run 스텝 열거가 비었다 — 스캔 0건은 통과가 아니다: {scanned}"
        assert unresolved == [], f"미러가 재현하지 않는 셸이 ci.yml에 생겼다: {unresolved}"
