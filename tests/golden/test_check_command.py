"""골든 패스 검사 명령(`golden/check.py`) 테스트 — GOLD-21.

세 가지를 지킨다.
1. 검사 명령의 스텝이 CI golden-path 잡의 검사 스텝과 **글자까지** 같다(로컬 초록 = CI 초록).
2. 범위 검사가 허용 경로 밖 변경을 잡고, 허용 경로 안 변경은 통과시킨다.
3. 집행 지점이 실제로 배선돼 있다(Stop 훅 · 읽기 전용 검토 에이전트).

DB도 LLM도 쓰지 않는다. 범위 검사는 임시 git 저장소를 만들어 실제 git으로 돌린다.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from golden import check

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"
_REVIEWER = _REPO_ROOT / ".claude" / "agents" / "golden-reviewer.md"

# CI 잡의 스텝 중 "검사 스텝"으로 보는 것: 이 도구들을 python -m 으로 부르는 한 줄 명령
_CHECK_TOOL = re.compile(r"^python -m (ruff|black|mypy|pytest|importlinter)\b")


# ── 1. CI와 같은 스텝 ────────────────────────────────────────────────────────
def _ci_check_commands() -> list[str]:
    """ci.yml golden-path 잡에서 검사 스텝의 run 명령만 순서대로 뽑는다."""
    workflow = yaml.safe_load(_CI_YML.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["golden-path"]["steps"]
    commands = []
    for step in steps:
        run = str(step.get("run", "")).strip()
        if "\n" not in run and (_CHECK_TOOL.match(run) or "lint-imports" in run):
            commands.append(run)
    return commands


def test_steps_match_ci_job() -> None:
    """검사 명령의 스텝 = CI golden-path 잡의 검사 스텝(순서·글자 동일)."""
    ci_commands = _ci_check_commands()
    assert ci_commands, "ci.yml golden-path 잡에서 검사 스텝을 하나도 못 찾았다(공허한 통과 금지)"
    assert [command for _, command in check.CI_STEPS] == ci_commands


def test_ci_job_runs_in_backend_dir() -> None:
    """검사 명령은 CI와 같은 폴더(src/backend)에서 돈다 — CI 쪽 폴더가 바뀌면 알아챈다."""
    workflow = yaml.safe_load(_CI_YML.read_text(encoding="utf-8"))
    job = workflow["jobs"]["golden-path"]
    assert job["defaults"]["run"]["working-directory"] == "src/backend"


def test_fast_steps_are_a_subset() -> None:
    """--fast가 고르는 이름이 실제 스텝에 있다(오타로 0개가 되면 빠른 검사가 공허해진다)."""
    names = {name for name, _ in check.CI_STEPS}
    assert check.FAST_STEPS
    assert names >= check.FAST_STEPS


def test_step_argv_uses_same_interpreter() -> None:
    """`python`을 지금 도는 인터프리터로 바꾼다(다른 가상환경의 python이 끼지 않게)."""
    argv = check.step_argv("python -m mypy --strict golden")
    assert argv == [sys.executable, "-m", "mypy", "--strict", "golden"]
    with pytest.raises(ValueError):
        check.step_argv("ruff check golden")


def test_all_steps_run_even_after_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """앞 스텝이 실패해도 뒤 스텝을 돌린다 — 안 돌린 검사가 통과처럼 보이지 않게."""
    marker = tmp_path / "second_ran.txt"
    steps = [
        ("first", [sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"]),
        ("second", [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ok')"]),
    ]
    results = check.run_steps(steps, cwd=tmp_path, log_dir=tmp_path)
    assert [r.returncode for r in results] == [3, 0]
    assert marker.read_text() == "ok"
    captured = capsys.readouterr()
    assert "FAIL first (exit 3" in captured.out
    assert "PASS second (exit 0" in captured.out
    assert "boom" in captured.err  # 실패 출력의 끝부분을 보여 준다
    assert (tmp_path / "first.log").read_text(encoding="utf-8").strip() == "boom"


def test_missing_tool_is_a_failure_with_fix_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """검사 도구가 없으면 건너뛰지 않고 실패하며, 설치 방법을 알려 준다."""
    argv = [sys.executable, "-m", "no_such_tool_for_golden_check"]
    result = check.run_step("ghost", argv, tmp_path, None)
    assert result.returncode != 0
    assert "고치는 법" in capsys.readouterr().err


# ── 2. 범위 검사 ─────────────────────────────────────────────────────────────
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write(repo: Path, rel: str, text: str = "x\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main에 옛 코드·골든 파일이 하나씩 있고, 작업 브랜치 `work`로 갈라진 임시 저장소."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    _write(root, "src/backend/whymath_backend/old.py")
    _write(root, "src/backend/golden/api.py")
    _write(root, "backlog/tasks/GOLD-99.yaml", _task_yaml("GOLD-99", "todo", "null", []))
    _commit(root, "base")
    _git(root, "checkout", "-q", "-b", "work")
    return root


def _task_yaml(task_id: str, status: str, session: str, paths: list[str]) -> str:
    """하네스 CLI가 쓰는 태스크 파일과 같은 모양(필요한 필드만)."""
    lines = [
        "# 빌드 하네스 태스크",
        f"id: {task_id}",
        f'title: "{task_id} 제목: 콜론이 든 제목"',
        f"status: {status}",
        "acceptance:",
        '  - "paths 아래가 아닌 목록 항목 — 범위로 읽히면 안 된다"',
    ]
    lines += ["paths:", *[f'  - "{p}"' for p in paths]] if paths else ["paths: []"]
    lines += [f"session: {session}", "notes: |-", "  session: 가짜줄은 들여쓰기라 무시된다", ""]
    return "\n".join(lines)


def _claim(repo: Path, task_id: str, paths: list[str]) -> None:
    """작업 브랜치가 태스크를 진행 중으로 잡은 상태를 만든다."""
    _write(repo, f"backlog/tasks/{task_id}.yaml", _task_yaml(task_id, "in_progress", "work", paths))


def _scope(repo: Path) -> check.ScopeResult:
    return check.check_scope(repo, "main", check.my_tasks(repo, check.current_branch(repo)))


def test_scope_passes_inside_golden(repo: Path) -> None:
    """골든 경로 안의 커밋·미커밋·새 파일은 통과한다."""
    _write(repo, "src/backend/golden/api.py", "changed\n")
    _commit(repo, "golden edit")
    _write(repo, "golden/LATER.md", "note\n")  # 새 파일(커밋 전)
    _write(repo, "tests/golden/test_new.py")
    _write(repo, "src/mobile/lib/golden/screen.dart")
    _write(repo, "src/mobile/lib/main_golden.dart")
    result = _scope(repo)
    assert len(result.changed) == 5
    assert result.outside == ()


def test_scope_catches_committed_edit_outside(repo: Path) -> None:
    """옛 코드를 고쳐 커밋하면 잡힌다."""
    _write(repo, "src/backend/whymath_backend/old.py", "changed\n")
    _commit(repo, "legacy edit")
    assert _scope(repo).outside == ("src/backend/whymath_backend/old.py",)


def test_scope_catches_uncommitted_and_untracked_outside(repo: Path) -> None:
    """커밋 전 수정과 새 파일(스크립트가 직접 쓴 파일 포함)도 잡힌다."""
    _write(repo, "src/backend/whymath_backend/old.py", "changed\n")
    _write(repo, "scripts/새 도구.py")  # 한글·공백 파일명
    assert _scope(repo).outside == (
        "scripts/새 도구.py",
        "src/backend/whymath_backend/old.py",
    )


def test_scope_catches_moving_legacy_into_golden(repo: Path) -> None:
    """옛 파일을 golden으로 '옮기는' 것도 옛 위치의 삭제라서 잡힌다."""
    _git(repo, "mv", "src/backend/whymath_backend/old.py", "src/backend/golden/old.py")
    _commit(repo, "move")
    assert _scope(repo).outside == ("src/backend/whymath_backend/old.py",)


def test_scope_ignores_main_moving_ahead(repo: Path) -> None:
    """갈라진 뒤 main에 들어온 남의 변경은 내 변경이 아니다(분기 지점 기준)."""
    _git(repo, "checkout", "-q", "main")
    _write(repo, "src/backend/whymath_backend/other.py")
    _commit(repo, "someone else on main")
    _git(repo, "checkout", "-q", "work")
    _write(repo, "golden/LATER.md")
    assert _scope(repo).outside == ()


def test_scope_does_not_match_lookalike_folders(repo: Path) -> None:
    """이름만 비슷한 폴더(golden_old/, tests/golden2/)는 골든 경로가 아니다."""
    _write(repo, "golden_old/a.md")
    _write(repo, "tests/golden2/test_a.py")
    _write(repo, "src/mobile/lib/main_golden.dart.bak")
    assert len(_scope(repo).outside) == 3


def test_scope_allows_paths_declared_on_my_task(repo: Path) -> None:
    """목록 밖 파일은 내 태스크 paths에 선언했을 때만 통과한다."""
    _write(repo, ".claude/agents/x.md")
    _write(repo, "docs/elsewhere.md")
    _claim(repo, "GOLD-99", [".claude/agents/*.md"])
    result = _scope(repo)
    assert result.task_ids == ("GOLD-99",)
    assert result.outside == ("docs/elsewhere.md",)


def test_scope_ignores_other_sessions_task_paths(repo: Path) -> None:
    """다른 세션의 태스크·끝난 태스크가 선언한 paths는 내 허용 범위가 아니다."""
    _write(repo, "docs/elsewhere.md")
    _write(
        repo,
        "backlog/tasks/GOLD-98.yaml",
        _task_yaml("GOLD-98", "in_progress", "other-branch", ["docs/**"]),
    )
    assert _scope(repo).outside == ("docs/elsewhere.md",)


def test_scope_ignores_tasks_finished_before_this_branch(repo: Path) -> None:
    """main에 이미 있던 끝난 태스크(이 브랜치가 건드리지 않음)의 paths는 허용 범위가 아니다."""
    _git(repo, "checkout", "-q", "main")
    _write(repo, "backlog/tasks/GOLD-97.yaml", _task_yaml("GOLD-97", "done", "null", ["docs/**"]))
    _commit(repo, "old finished task on main")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "-q", "main")
    _write(repo, "docs/elsewhere.md")
    assert _scope(repo).outside == ("docs/elsewhere.md",)


def test_scope_keeps_paths_of_task_finished_on_this_branch(repo: Path) -> None:
    """이 브랜치에서 완료 처리한 태스크의 paths는 머지 전까지 계속 인정한다.

    `backlog.py done`은 status=done · session=null로 바꾼다. 그 뒤에도 그 태스크가 선언하고
    바꾼 파일은 변경 목록에 남으므로, 인정하지 않으면 정상 변경이 위반으로 잡힌다.
    """
    _claim(repo, "GOLD-99", ["docs/**"])
    _write(repo, "docs/elsewhere.md")
    _commit(repo, "work under GOLD-99")
    assert _scope(repo).outside == ()
    _write(repo, "backlog/tasks/GOLD-99.yaml", _task_yaml("GOLD-99", "done", "null", ["docs/**"]))
    assert check.my_tasks(repo, "work") == ()  # 진행 중 목록에서는 빠졌다
    assert _scope(repo).outside == ()
    _write(repo, "scripts/other.py")  # 그 태스크가 선언하지 않은 파일은 여전히 잡힌다
    assert _scope(repo).outside == ("scripts/other.py",)


def test_parse_task_reads_only_top_level_fields() -> None:
    """acceptance 목록·notes 속 가짜 줄을 paths·session으로 읽지 않는다."""
    task = check.parse_task(_task_yaml("GOLD-99", "in_progress", "work", ["a/**", "b.py"]))
    assert task == check.Task("GOLD-99", "in_progress", "work", ("a/**", "b.py"))
    empty = check.parse_task(_task_yaml("GOLD-99", "todo", "null", []))
    assert empty.session == "" and empty.paths == ()


def test_parse_task_reads_real_ledger_files() -> None:
    """실제 대장의 골든 태스크를 읽어 PyYAML 결과와 같은지 본다(형식이 바뀌면 알아챈다)."""
    files = sorted((_REPO_ROOT / "backlog" / "tasks").glob("GOLD-*.yaml"))
    assert files, "골든 태스크 파일을 하나도 못 찾았다(공허한 통과 금지)"
    for path in files:
        text = path.read_text(encoding="utf-8")
        expected = yaml.safe_load(text)
        task = check.parse_task(text)
        assert task.task_id == expected["id"]
        assert task.status == expected["status"]
        assert task.session == (expected.get("session") or "")
        assert list(task.paths) == list(expected.get("paths") or [])


def test_scope_message_tells_how_to_fix(repo: Path) -> None:
    """안내문에 틀린 파일·허용 경로·고치는 법(되돌리기 / 대장 선언 명령)이 다 있다."""
    _claim(repo, "GOLD-99", [])
    _write(repo, "docs/elsewhere.md")
    message = check.scope_message(_scope(repo))
    assert "docs/elsewhere.md" in message
    assert "golden/**" in message
    assert "되돌립니다" in message
    assert "backlog.py amend GOLD-99" in message


def test_run_scope_exit_codes(repo: Path, tmp_path: Path) -> None:
    """통과 0 · 위반 1 · 판정 불가 3(기준 브랜치가 없으면 통과가 아니라 판정 불가)."""
    assert check.run_scope(repo, "main") == 0
    assert check.run_scope(repo, "no-such-base") == 3
    _write(repo, "docs/elsewhere.md")
    assert check.run_scope(repo, "main") == 1


# ── 전체 판정(종료 코드) ─────────────────────────────────────────────────────
_FAKE_STEPS = (("ok", "python -c pass"), ("bad", "python -m no_such_tool_for_golden_check"))


def test_run_checks_fails_when_any_step_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """스텝 하나라도 실패하면 명령 전체가 1로 끝나고, 판정 줄이 실패한 이름을 적는다."""
    monkeypatch.setattr(check, "CI_STEPS", _FAKE_STEPS)
    assert check.run_checks(repo, "main", fast=False) == 1
    out = capsys.readouterr().out
    assert "GOLDEN_CHECK=FAIL" in out and "실패: bad" in out
    assert "PASS ok" in out and "FAIL bad" in out


def test_run_checks_passes_only_when_everything_passes(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """전부 통과하면 0. 스텝이 다 통과해도 범위 위반이 있으면 1이다."""
    monkeypatch.setattr(check, "CI_STEPS", _FAKE_STEPS[:1])
    assert check.run_checks(repo, "main", fast=False) == 0
    assert "GOLDEN_CHECK=PASS" in capsys.readouterr().out
    _write(repo, "docs/elsewhere.md")
    assert check.run_checks(repo, "main", fast=False) == 1
    assert "실패: scope" in capsys.readouterr().out


def test_fast_names_the_steps_it_did_not_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--fast는 고른 스텝만 돌리고, 안 돌린 스텝의 이름을 판정 줄에 적는다."""
    monkeypatch.setattr(check, "CI_STEPS", _FAKE_STEPS)
    monkeypatch.setattr(check, "FAST_STEPS", frozenset({"ok"}))
    assert check.run_checks(repo, "main", fast=True) == 0  # 실패할 bad는 돌리지 않았다
    out = capsys.readouterr().out
    assert "FAIL bad" not in out
    assert "안 돌림(--fast): bad" in out


def test_main_scope_mode_returns_scope_exit_code(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """명령줄 진입점이 범위 검사의 종료 코드를 그대로 돌려준다."""
    monkeypatch.setattr(check, "repo_root", lambda _start: repo)
    monkeypatch.setenv("GOLDEN_SCOPE_BASE", "main")
    assert check.main(["--scope"]) == 0
    assert "GOLDEN_SCOPE=PASS" in capsys.readouterr().out
    _write(repo, "docs/elsewhere.md")
    assert check.main(["--scope"]) == 1
    assert "GOLDEN_SCOPE=FAIL" in capsys.readouterr().out


# ── Stop 훅 ──────────────────────────────────────────────────────────────────
def test_hook_blocks_golden_session_outside_scope(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """골든 태스크 진행 중 + 범위 밖 변경 → 정지를 막는다(exit 2)."""
    _claim(repo, "GOLD-99", [])
    _write(repo, "docs/elsewhere.md")
    assert check.hook_stop(repo, "main", b"{}") == 2
    assert "docs/elsewhere.md" in capsys.readouterr().err


def test_hook_passes_golden_session_inside_scope(repo: Path) -> None:
    """골든 태스크 진행 중이어도 범위 안이면 통과한다."""
    _claim(repo, "GOLD-99", [])
    _write(repo, "golden/LATER.md")
    assert check.hook_stop(repo, "main", b"{}") == 0


def test_hook_ignores_non_golden_sessions(repo: Path) -> None:
    """골든 태스크가 없는 세션(옛 코드를 고치는 다른 트랙)은 막지 않는다."""
    _write(repo, "docs/elsewhere.md")
    assert check.hook_stop(repo, "main", b"{}") == 0  # 진행 중 태스크 없음
    _write(
        repo,
        "backlog/tasks/OPS-1.yaml",
        _task_yaml("OPS-1", "in_progress", "work", ["src/**"]),
    )
    assert check.hook_stop(repo, "main", b"{}") == 0  # 골든이 아닌 태스크


def test_hook_does_not_loop_or_hold_hostage(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """이미 한 번 막은 재정지·판정 불가·깨진 입력은 통과한다(판정 불가는 이유를 남긴다)."""
    _claim(repo, "GOLD-99", [])
    _write(repo, "docs/elsewhere.md")
    assert check.hook_stop(repo, "main", json.dumps({"stop_hook_active": True}).encode()) == 0
    assert check.hook_stop(repo, "main", b"\xff not json") == 2  # 깨진 입력은 빈 입력으로 읽는다
    capsys.readouterr()
    assert check.hook_stop(repo, "no-such-base", b"{}") == 0
    assert "판정 불가" in capsys.readouterr().err
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    assert check.hook_stop(not_a_repo, "main", b"{}") == 0


# ── 3. 집행 지점 배선 ────────────────────────────────────────────────────────
def test_stop_hook_is_wired() -> None:
    """Stop 훅이 범위 검사를 실제로 부른다 — 스크립트만 있고 아무도 안 부르는 상태를 막는다."""
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for group in settings["hooks"]["Stop"]
        for hook in group["hooks"]
        if hook.get("type") == "command"
    ]
    wired = [c for c in commands if "src/backend/golden/check.py" in c and "--hook-stop" in c]
    assert len(wired) == 1, commands
    assert (_REPO_ROOT / "src" / "backend" / "golden" / "check.py").is_file()


def test_script_runs_without_installed_dependencies() -> None:
    """훅은 의존성을 설치하지 않은 세션에서도 돈다 — 표준 라이브러리만 import한다."""
    source = (_REPO_ROOT / "src" / "backend" / "golden" / "check.py").read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:from|import)\s+([a-zA-Z_]+)", source, re.MULTILINE))
    assert imported, "import 줄을 하나도 못 찾았다(공허한 통과 금지)"
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported
    done = subprocess.run(
        # -I: 사이트 패키지·현재 폴더를 빼고 돈다. 골든이 아닌 임시 폴더에서 훅 모드로 부른다.
        [sys.executable, "-I", str(_REPO_ROOT / "src/backend/golden/check.py"), "--hook-stop"],
        input=b"{}",
        capture_output=True,
        cwd=_REPO_ROOT,
        check=False,
    )
    assert done.returncode in (0, 2), done.stderr.decode("utf-8", errors="replace")


def test_reviewer_agent_is_read_only() -> None:
    """검토 에이전트는 읽기·검색 도구만 가진다 — 고칠 수 있으면 심사가 아니라 작성이 된다."""
    text = _REVIEWER.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["name"] == "golden-reviewer"
    tools = {tool.strip() for tool in str(front["tools"]).split(",")}
    assert tools == {"Read", "Grep", "Glob"}
    body = text.split("---\n", 2)[2]
    for required in ("인수 기준", "범위 밖", "스타일은 건너뜁니다", "반려"):
        assert required in body, required
