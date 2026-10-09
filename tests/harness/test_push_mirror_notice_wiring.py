"""푸시·PR 생성 시점 CI 미러 고지의 **집행 지점** 배선 동결 (HARN-209 acceptance ④).

"고지 함수가 존재한다"와 "그 경로를 실제 도구 호출이 지난다"는 다르다 — 이 파일은 후자를 묻는다.
정본화(판정 로직 = `test_push_mirror_notice.py`)와 집행 지점(훅 등록·호출 사슬·PR 본문 첨부 경로)을
별항으로 분리한다 (CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지").

  동결하는 것                           깨지면 생기는 일
  ────────────────────────────────────────────────────────────────────────────────────────
  settings.json 등록(Bash·PR 생성 매처)  판정 로직은 멀쩡한데 어떤 도구 호출에서도 안 불린다
  등록된 **명령 문자열 그대로** 실행     $CLAUDE_PROJECT_DIR 경로·인터프리터가 틀려도 단위 테스트는 초록
  훅 → 진입점 → 판정·본문 섹션 호출 사슬   고지문은 나가는데 PR 본문 섹션이 사슬에서 빠진다
  additionalContext JSON(ASCII)          stdout 평문은 PreToolUse에서 모델에 안 간다(공식 문서) —
                                         평문으로 내면 고지가 영영 안 보인다
  종료 코드 항상 0                       고지 훅이 푸시·PR 생성을 막는 훅으로 변질
  평가 한 건당 로그 한 줄                습관화 감시(판정 문서 §6)의 입력이 사라짐
  /drive 절차가 섹션 생성 경로를 가리킴   PR을 여는 절차가 이 경로를 모른다
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import ci_mirror
import push_mirror_notice as pmn
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"
_HOOK = _REPO_ROOT / ".claude" / "hooks" / "push_mirror_notice.py"
_MODULE = _REPO_ROOT / "scripts" / "harness" / "push_mirror_notice.py"
_DRIVE = _REPO_ROOT / ".claude" / "commands" / "drive.md"
_PR_TOOL = "mcp__github__create_pull_request"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="실제 git이 필요하다")


# ── 등록 ─────────────────────────────────────────────────────────────────────
def _registered_entries() -> list[dict]:
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    entries = []
    for block in settings["hooks"]["PreToolUse"]:
        for hook in block["hooks"]:
            if "push_mirror_notice.py" in hook.get("command", ""):
                entries.append({"matcher": block.get("matcher", ""), **hook})
    return entries


def test_hook_is_registered_exactly_once_for_push_and_pr_create() -> None:
    entries = _registered_entries()
    assert len(entries) == 1, f"등록이 {len(entries)}건 — 중복 등록은 고지를 두 번 낸다"
    (entry,) = entries
    matchers = set(entry["matcher"].split("|"))
    assert {"Bash", _PR_TOOL} <= matchers
    assert entry["type"] == "command" and _HOOK.is_file()
    assert (
        0 < entry.get("timeout", 600) <= 120
    ), "시간 초과 시 도구 호출은 막히지 않으므로 짧게 둔다"


# ── 호출 사슬 (AST) ──────────────────────────────────────────────────────────
def _called_names(func: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} 없음")


def test_call_chain_from_hook_to_pr_section() -> None:
    hook = ast.parse(_HOOK.read_text(encoding="utf-8"))
    main_calls = _called_names(_function(hook, "main"))
    assert {"notice_for_push", "notice_for_pr_create"} <= main_calls

    module = ast.parse(_MODULE.read_text(encoding="utf-8"))
    push_calls = _called_names(_function(module, "notice_for_push"))
    assert {"plan_from_command", "assess", "_with_notice"} <= push_calls
    pr_calls = _called_names(_function(module, "notice_for_pr_create"))
    assert {"assess", "body_has_section", "_with_notice"} <= pr_calls
    # PR 본문 첨부가 불리는 경로: 진입점 → _with_notice → render_pr_section · render_notice
    notice_calls = _called_names(_function(module, "_with_notice"))
    assert {"compute_reach", "render_pr_section", "render_notice"} <= notice_calls


def test_hook_never_blocks() -> None:
    """고지 훅은 반환값이 0뿐이다 — 거부(2)나 비정상 종료 코드로의 변질을 막는다."""
    tree = ast.parse(_HOOK.read_text(encoding="utf-8"))
    values = {
        node.value.value if isinstance(node.value, ast.Constant) else "<식>"
        for node in ast.walk(_function(tree, "main"))
        if isinstance(node, ast.Return) and node.value is not None
    }
    assert values == {0}
    source = _HOOK.read_text(encoding="utf-8")
    assert (
        "permissionDecision" not in source
    ), "권한 결정을 건드리면 사용자의 권한 흐름을 우회할 수 있다"
    assert "updatedInput" not in source


def test_drive_command_points_at_the_pr_section_generator() -> None:
    text = _DRIVE.read_text(encoding="utf-8")
    assert "push_mirror_notice.py pr-section" in text
    assert pmn.SECTION_HEADING in text


# ── 등록된 명령 문자열 그대로 실행 ───────────────────────────────────────────────
def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *argv],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text(".claude/cache/\n.claude/logs/\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-q", "-b", "feature")
    (root / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "feature")
    return root


def _mirror_pass(repo: Path) -> None:
    payload = {
        "schema": ci_mirror.RESULT_SCHEMA,
        "commit": _git(repo, "rev-parse", "HEAD"),
        "jobs": [
            {"name": "harness-integrity", "exit": 0, "steps": [{"name": "s", "status": "passed"}]}
        ],
        "not_executed": 0,
        "exit": 0,
        "tainted": False,  # schema 3(HARN-194)
    }
    path = repo / ci_mirror.DEFAULT_RESULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_registered(
    repo: Path, event: dict, *, raw: bytes | None = None, env_extra: dict | None = None
) -> subprocess.CompletedProcess[bytes]:
    """settings.json에 **등록된 명령 문자열**을 셸로 실행한다 (`$CLAUDE_PROJECT_DIR`는 실제 저장소)."""
    (entry,) = _registered_entries()
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(_REPO_ROOT), **(env_extra or {})}
    payload = raw if raw is not None else json.dumps({"cwd": str(repo), **event}).encode("utf-8")
    return subprocess.run(
        entry["command"], shell=True, input=payload, capture_output=True, cwd=repo, env=env
    )


def _log_rows(repo: Path) -> list[dict]:
    path = repo / ".claude" / "logs" / "push_mirror_notices.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _push(command: str = "git push -u origin feature") -> dict:
    return {"tool_name": "Bash", "session_id": "s1", "tool_input": {"command": command}}


class TestRegisteredCommandEndToEnd:
    def test_unmirrored_push_emits_additional_context_json(self, repo: Path) -> None:
        proc = _run_registered(repo, _push())
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        out = json.loads(proc.stdout.decode("utf-8"))
        spec = out["hookSpecificOutput"]
        assert spec["hookEventName"] == "PreToolUse"
        assert "[CI 미러 고지 · 푸시 직전]" in spec["additionalContext"]
        assert set(spec) == {"hookEventName", "additionalContext"}, "권한 결정 필드를 섞지 않는다"
        rows = _log_rows(repo)
        assert [(r["code"], r["notified"], r["deduped"]) for r in rows] == [
            ("no_result", True, False)
        ]

    def test_same_commit_and_reason_is_notified_once_but_logged_every_time(
        self, repo: Path
    ) -> None:
        first = _run_registered(repo, _push())
        second = _run_registered(repo, _push())
        assert (
            first.stdout and not second.stdout
        ), "재시도 푸시에 같은 고지를 되풀이하면 소음이 된다"
        rows = _log_rows(repo)
        assert [(r["notified"], r["deduped"]) for r in rows] == [(True, False), (False, True)]

    def test_mirrored_push_is_silent_but_still_logged(self, repo: Path) -> None:
        """대조군 — 침묵한 평가도 기록된다(고지 비율의 분모)."""
        _mirror_pass(repo)
        proc = _run_registered(repo, _push())
        assert proc.returncode == 0 and proc.stdout == b""
        (row,) = _log_rows(repo)
        assert row["code"] == "mirror_pass" and row["notified"] is False and row["head"]

    def test_unrelated_calls_are_not_evaluated(self, repo: Path) -> None:
        for event in (
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            {"tool_name": "Edit", "tool_input": {"command": "git push"}},
            {"tool_name": "mcp__github__list_pull_requests", "tool_input": {}},
        ):
            proc = _run_registered(repo, event)
            assert proc.returncode == 0 and proc.stdout == b""
        assert _log_rows(repo) == []

    def test_pr_create_with_missing_section_carries_the_pasteable_block(self, repo: Path) -> None:
        _mirror_pass(repo)
        event = {
            "tool_name": _PR_TOOL,
            "tool_input": {"head": "feature", "base": "main", "title": "t", "body": "요약만"},
        }
        proc = _run_registered(repo, event)
        context = json.loads(proc.stdout.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
        assert "[CI 미러 고지 · PR 생성 직전]" in context
        assert pmn.SECTION_HEADING in context and pmn.SECTION_MARKER in context
        (row,) = _log_rows(repo)
        assert row["trigger"] == "pr_create" and row["code"] == "body_missing_section"

    def test_output_survives_a_cp949_console(self, repo: Path) -> None:
        """한국어 Windows(cp949) 표준 입출력에서도 JSON이 손상되지 않는다 — 출력은 순수 ASCII."""
        command = 'git commit -m "한글 — 설명" && git push'
        proc = _run_registered(
            repo, _push(command), env_extra={"PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"}
        )
        assert proc.returncode == 0, proc.stderr.decode("cp949", "replace")
        assert proc.stdout.decode("ascii")  # 비ASCII가 있으면 UnicodeDecodeError
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "푸시 직전" in context

    def test_log_never_contains_the_command_text(self, repo: Path) -> None:
        secret = "TOKEN-되면-안-남는-값"
        _run_registered(repo, _push(f"git push https://x:{secret}@example.com/r.git"))
        log = (repo / ".claude" / "logs" / "push_mirror_notices.jsonl").read_text(encoding="utf-8")
        assert secret not in log and "example.com" not in log

    def test_push_glued_to_a_preceding_command_is_still_evaluated(self, repo: Path) -> None:
        """실사용 반례(2026-10-08) — `head;`처럼 단어에 붙은 세미콜론 뒤의 푸시가 `not_a_push`로 놓쳤다."""
        _mirror_pass(repo)
        command = "ls -a 2>&1 | head; git push -u origin feature 2>&1 | tail -3; echo done"
        proc = _run_registered(repo, _push(command))
        assert proc.returncode == 0 and proc.stdout == b""
        (row,) = _log_rows(repo)
        assert row["code"] == "mirror_pass", "붙은 `;` 뒤의 푸시가 평가되지 않았다"

    def test_command_that_only_mentions_push_is_not_logged(self, repo: Path) -> None:
        """ "push"라는 낱말만 든 명령은 평가된 푸시가 아니다 — 로그(고지 비율의 분모)에 남기지 않는다."""
        for command in ("grep -rn push scripts", "git log --grep push", "echo git push"):
            proc = _run_registered(repo, _push(command))
            assert proc.returncode == 0 and proc.stdout == b""
        assert _log_rows(repo) == []

    def test_garbage_stdin_passes_with_the_error_type_named(self, repo: Path) -> None:
        proc = _run_registered(repo, {}, raw=b"\xff\xfe not json")
        assert proc.returncode == 0 and proc.stdout == b""
        assert "JSONDecodeError" in proc.stderr.decode("utf-8", "replace")


def _load_hook():
    spec = importlib.util.spec_from_file_location("push_mirror_notice_hook", _HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_non_push_bash_does_not_even_resolve_the_repository(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """선거름 — 모든 Bash 호출마다 git 조회·모듈 임포트를 하면 도구 호출마다 지연이 붙는다."""
    hook = _load_hook()

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("push가 없는 Bash 호출에서 저장소를 조회했다")

    monkeypatch.setattr(hook, "_project_root", must_not_run)
    payload = json.dumps({"cwd": str(repo), **_push("ls -la")}).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(payload)})())
    assert hook.main() == 0


def test_evaluation_error_does_not_block_and_names_the_type(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """평가가 예외를 내도 푸시를 막지 않는다 — 다만 침묵하지 않는다(타입명 + 로그)."""
    hook = _load_hook()

    def boom(*_args, **_kwargs):
        raise RuntimeError("의도한 실패")

    monkeypatch.setattr(pmn, "notice_for_push", boom)
    payload = json.dumps({"cwd": str(repo), **_push()}).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(payload)})())
    assert hook.main() == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "RuntimeError" in captured.err
    (row,) = _log_rows(repo)
    assert row["code"] == "hook_error" and row["error_type"] == "RuntimeError"
