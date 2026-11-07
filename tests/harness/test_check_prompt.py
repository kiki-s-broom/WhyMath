"""HARN-321 — 요청 단계 범위 대조 훅(`backlog.py check-prompt`).

분기마다 그 분기가 없으면 실패하는 입력을 둔다:
- claim 있음 / 없음 / main 브랜치
- 언급 ID 4상태(다른 세션 claim · done/cancelled · 대장에 없음 · todo) + 내 claim(중복 표시 안 함)
- 비태스크 표기(UTF-8·R18-02)는 무시 — 대조군
- 깨진 stdin · 대장 부재 · 내부 예외 → 전부 exit 0
- 지연: 내 claim·언급 ID 파일만 파싱한다(대장 전체 로드 금지)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import prompt_scope
import pytest
from _hook_stdin import set_hook_stdin

import backlog as cli

BRANCH = "claude/my-session"


def _task(
    root: Path,
    task_id: str,
    *,
    status: str = "todo",
    session: str | None = None,
    paths: list[str] | None = None,
    filename: str | None = None,
) -> None:
    tasks = root / "backlog" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    path_lines = "".join(f"  - {p}\n" for p in (paths or []))
    text = (
        f"id: {task_id}\n"
        f'title: "{task_id} 제목"\n'
        f"status: {status}\n"
        + ("paths:\n" + path_lines if path_lines else "paths: []\n")
        + f"session: {session if session else 'null'}\n"
        "notes: x\n"
    )
    (tasks / (filename or f"{task_id}.yaml")).write_text(text, encoding="utf-8")


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    _task(
        tmp_path,
        "HARN-1-mine",
        status="in_progress",
        session=BRANCH,
        paths=["scripts/a.py", "scripts/b.py", "c.py", "d.py", "e.py"],
    )
    _task(tmp_path, "EOS-2", status="in_progress", session="claude/other")
    _task(tmp_path, "OPS-3-old", status="done")
    _task(tmp_path, "OPS-4", status="cancelled")
    _task(tmp_path, "P3-5", status="todo")
    return tmp_path


def _text(root: Path, prompt: str, branch: str = BRANCH) -> str:
    return "\n".join(prompt_scope.build_context(root, branch, prompt))


class TestClaimLine:
    def test_shows_my_claim_with_paths_truncated(self, ledger: Path):
        out = _text(ledger, "아무 요청")
        assert "이 세션 claim: HARN-1-mine" in out
        assert "scripts/a.py, scripts/b.py, c.py, d.py 외 1" in out
        assert "add" in out and "amend" in out

    def test_no_claim_tells_start_first(self, ledger: Path):
        out = _text(ledger, "아무 요청", branch="claude/idle")
        assert "claim 없음" in out
        assert "backlog.py start" in out
        assert "HARN-1-mine" not in out

    def test_main_branch_never_counts_as_claim(self, tmp_path: Path):
        _task(tmp_path, "HARN-9", status="in_progress", session="main")
        assert "claim 없음" in _text(tmp_path, "x", branch="main")

    def test_session_text_match_requires_status_in_progress(self, tmp_path: Path):
        # session 줄은 맞지만 상태가 review — claim으로 세지 않는다
        _task(tmp_path, "HARN-8", status="review", session=BRANCH)
        assert "claim 없음" in _text(tmp_path, "x")

    def test_branch_prefix_is_not_a_match(self, tmp_path: Path):
        # 'claude/my-session-2' 는 'claude/my-session' 의 claim 이 아니다(줄 끝까지 일치)
        _task(tmp_path, "HARN-7", status="in_progress", session=BRANCH + "-2")
        assert "claim 없음" in _text(tmp_path, "x")


class TestMentions:
    def test_other_session_claim(self, ledger: Path):
        out = _text(ledger, "EOS-2 해줘")
        assert "EOS-2: 다른 세션이 claim 중(claude/other" in out
        assert "착수 금지" in out

    @pytest.mark.parametrize("task_id,status", [("OPS-3", "done"), ("OPS-4", "cancelled")])
    def test_closed_tasks_point_to_followup(self, ledger: Path, task_id: str, status: str):
        out = _text(ledger, f"{task_id} 다시")
        assert f"{task_id}: {status}" in out
        assert "후속 태스크" in out

    def test_missing_id_is_not_declared_absent(self, ledger: Path):
        out = _text(ledger, "HARN-404 상태는?")
        assert "HARN-404: 로컬 대장에 없음" in out
        assert "git log --all --grep=HARN-404" in out

    def test_todo_not_mine_requires_start(self, ledger: Path):
        out = _text(ledger, "P3-5 진행")
        assert "P3-5: todo (이 세션 claim 아님)" in out
        assert "backlog.py start P3-5" in out

    def test_my_claim_is_not_repeated(self, ledger: Path):
        # 문구가 무엇이든 줄이 더 붙으면 실패한다 — 표제 + claim 1줄 + 안내 1줄
        lines = prompt_scope.build_context(ledger, BRANCH, "HARN-1 계속")
        assert len(lines) == 3, lines

    def test_non_task_tokens_are_ignored(self, ledger: Path):
        # 대조군: 접두어가 대장에 없으면 '대장에 없음'으로 오보하지 않는다
        out = _text(ledger, "UTF-8 과 R18-02, ISO-8601 은 태스크가 아니다")
        assert "언급 ID" not in out

    def test_lookup_does_not_take_longer_number(self, ledger: Path):
        # HARN-1 을 물었는데 HARN-10-other(done) 를 집어 오면 안 된다 — 파일명 경계 절의 반례
        _task(ledger, "HARN-10-other", status="done")
        out = _text(ledger, "HARN-1 계속")
        assert "done" not in out

    def test_lookup_without_exact_match_reports_absent(self, ledger: Path):
        # 정확한 HARN-2 가 없고 HARN-20 만 있을 때 — 정렬 순서 덕에 우연히 맞는 일이 없는 반례
        _task(ledger, "HARN-20-other", status="done")
        out = _text(ledger, "HARN-2 상태")
        assert "HARN-2: 로컬 대장에 없음" in out
        assert "done" not in out

    def test_regex_digit_boundary(self, ledger: Path):
        # 다섯 자리 'HARN-12345' 를 'HARN-1234' 로 잘라 읽으면 없는 ID 를 지어낸다 — 정규식 경계 절의 반례
        assert "언급 ID" not in _text(ledger, "HARN-12345")

    def test_mentions_are_capped(self, ledger: Path):
        prompt = " ".join(f"HARN-{n}00" for n in range(1, 10))
        assert _text(ledger, prompt).count("언급 ID") == prompt_scope._MAX_MENTIONS

    def test_lookup_resolves_slugless_filename(self, tmp_path: Path):
        _task(tmp_path, "MP-6", status="done", filename="MP-6.yaml")
        assert "MP-6: done" in _text(tmp_path, "MP-6")


class TestParsesOnlyWhatItNeeds:
    def test_does_not_parse_whole_ledger(self, ledger: Path, monkeypatch):
        # 무관한 태스크 200건을 더한다 — 파싱 횟수는 내 claim 1 + 언급 1 이어야 한다
        for n in range(200):
            _task(ledger, f"S4-{n + 100}", status="todo")
        calls: list[Path] = []
        real = prompt_scope._parse
        monkeypatch.setattr(prompt_scope, "_parse", lambda p: (calls.append(p), real(p))[1])
        prompt_scope.build_context(ledger, BRANCH, "P3-5 확인")
        assert sorted(p.name for p in calls) == ["HARN-1-mine.yaml", "P3-5.yaml"]


class TestHookEntry:
    """실제 훅 진입점 — 어떤 실패에서도 exit 0."""

    @pytest.fixture
    def repo(self, git_repo: Path, ledger: Path, monkeypatch) -> Path:
        # git_repo 와 ledger 는 같은 tmp_path 다 — 대장이 이미 저장소 안에 있다
        assert ledger == git_repo and (git_repo / "backlog" / "tasks").is_dir()
        subprocess.run(["git", "checkout", "-q", "-b", BRANCH], cwd=git_repo, check=True)
        monkeypatch.chdir(git_repo)
        return git_repo

    def test_prints_context_and_exits_zero(self, repo: Path, monkeypatch, capsys):
        set_hook_stdin(monkeypatch, '{"prompt": "EOS-2 — 한글 포함"}')
        assert cli.main(["check-prompt"]) == 0
        out = capsys.readouterr().out
        assert "이 세션 claim: HARN-1-mine" in out
        assert "EOS-2: 다른 세션이 claim 중" in out

    @pytest.mark.parametrize("raw", ["not json", "", "[1, 2]", '{"prompt": null}'])
    def test_broken_stdin_still_exits_zero(self, repo: Path, monkeypatch, capsys, raw: str):
        set_hook_stdin(monkeypatch, raw)
        assert cli.main(["check-prompt"]) == 0
        assert "이 세션 claim: HARN-1-mine" in capsys.readouterr().out

    def test_internal_error_reports_type_and_exits_zero(self, repo: Path, monkeypatch, capsys):
        def boom(*_a, **_k):
            raise PermissionError("x")

        monkeypatch.setattr(prompt_scope, "build_context", boom)
        set_hook_stdin(monkeypatch, '{"prompt": "x"}')
        assert cli.main(["check-prompt"]) == 0
        assert "판정 불가 — PermissionError" in capsys.readouterr().out

    def test_missing_tasks_dir_exits_zero(self, repo: Path, monkeypatch, capsys):
        subprocess.run(["rm", "-rf", str(repo / "backlog" / "tasks")], check=True)
        set_hook_stdin(monkeypatch, '{"prompt": "HARN-1"}')
        assert cli.main(["check-prompt"]) == 0
        assert "claim 없음" in capsys.readouterr().out


def test_settings_wires_hook_without_blocking():
    """배선 동결 — UserPromptSubmit 에 check-prompt 가 있고, 실패해도 막지 않는 형태다."""
    import json

    root = Path(__file__).resolve().parents[2]
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        h.get("command", "") for m in settings["hooks"]["UserPromptSubmit"] for h in m["hooks"]
    ]
    wired = [c for c in commands if 'backlog.py" check-prompt' in c]
    assert len(wired) == 1
    assert wired[0].rstrip().endswith("|| true")
