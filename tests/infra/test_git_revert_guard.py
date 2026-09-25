"""HARN-136 — git 원복 계열 가드의 변별력 동결.

**왜 이 가드가 있는가**: `git checkout -- <경로>` · `git restore` · `git stash` 는
미커밋 작업분을 **무증상으로** 지운다(에러도 경고도 없다). 이 저장소에서 두 번 났다 —
2026-08-10 `OPS-24`(미커밋 구현분 +59/-6 소실) · 2026-09-22 `EOS-128`(이벤트 약 10건
소실). 1회차 대책이 CLAUDE.md 산문이었고 문면이 "뮤테이션 원복"으로 좁아 일반 정리
작업에는 적용되지 않는 것처럼 읽혔다 — 그래서 2회차 대책은 코드다.

**이 파일이 지키는 급소 둘** (acceptance ③):
  ① **정상에서 침묵한다** — 탐지 기준이 "git 원복 명령인가"가 아니라 "그 경로에
     잃을 것이 있는가"이므로, 깨끗한 트리·브랜치 전환·조회 명령에서는 한 번도
     발화하지 않아야 한다. 전건 차단하면 사람이 게이트를 끈다.
  ② **위반에서 실제로 막는다** — 대상 경로에 미커밋 변경이 있으면 exit 2.

두 방향을 **둘 다** 재지 않으면 어느 한쪽으로 쏠린 구현이 통과한다: 전건 통과는
①만으로, 전건 차단은 ②만으로 초록이 된다.

hermetic: 진짜 git 저장소를 tmp_path에 만들어 쓴다 — 네트워크·DB 0.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _REPO_ROOT / ".claude" / "hooks" / "git_revert_guard.py"
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"


def _load_guard():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("git_revert_guard", _GUARD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def _git(*argv: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """커밋 1개를 가진 진짜 git 저장소. 가드는 실제 `git status` 를 부르므로 시임이 아니다."""
    _git("init", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "t@whymath.local", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / "keep.txt").write_text("원본\n", encoding="utf-8")
    (tmp_path / "backlog").mkdir()
    (tmp_path / "backlog" / "events.ndjson").write_text('{"a":1}\n', encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-m", "init", cwd=tmp_path)
    return tmp_path


def _run(command: str, cwd: Path, escape: str = "") -> subprocess.CompletedProcess[str]:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command + escape},
        "cwd": str(cwd),
        "session_id": "test",
    }
    return subprocess.run(
        [sys.executable, str(_GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=60,
    )


def _dirty(repo: Path) -> None:
    (repo / "backlog" / "events.ndjson").write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")


def test_guard_file_exists_and_is_executable() -> None:
    """스캔 0건은 실패 — 가드가 없으면 아래 단언이 전부 공허하다."""
    assert _GUARD.is_file(), f"가드가 없다: {_GUARD}"


def test_guard_is_wired_into_settings() -> None:
    """acceptance ⑤ — "파일이 존재함"과 "돌아감"은 다르다.

    이 프로젝트에서 반복 발생한 부류다(tests/infra 199건이 어떤 잡도 실행하지 않던
    상태, 브랜치 보호 required check가 통째로 미강제였던 상태). 등록을 기계가 동결한다.
    """
    cfg = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    pre = cfg.get("hooks", {}).get("PreToolUse", [])
    commands = [
        h.get("command", "")
        for entry in pre
        if entry.get("matcher") == "Bash"
        for h in entry.get("hooks", [])
    ]
    assert any(
        "git_revert_guard.py" in c for c in commands
    ), "PreToolUse(Bash)에 가드가 등록돼 있지 않다 — 파일만 있고 돌지 않는다"


class TestSilentWhenNothingToLose:
    """① 정상에서 침묵한다 — 이 묶음이 없으면 '전건 차단'이 통과한다."""

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout -- backlog/events.ndjson",  # 깨끗한 경로
            "git checkout .",
            "git restore keep.txt",
            "git stash",
            "git status",  # 원복 계열이 아니다
            "git checkout main",  # 브랜치 전환 — 경로가 아니다
            "git checkout -b feature/new",  # 브랜치 생성
            "git checkout -B feature/new origin/main",
            "git stash list",  # 조회
            "git stash pop",  # 되살리기 — 잃는 게 아니라 얻는 동작
            "python3 -m pytest tests/harness -q",  # git이 아예 아니다
            "echo 'git checkout -- x'",  # 낱말만 있고 실행은 echo다
        ],
    )
    def test_clean_tree_never_blocks(self, repo: Path, command: str) -> None:
        result = _run(command, repo)
        assert result.returncode == 0, (
            f"정상 명령을 막았다: {command}\n{result.stderr}\n"
            "상시 발화하는 게이트는 사람이 꺼 버린다"
        )

    def test_dirty_elsewhere_does_not_block_unrelated_path(self, repo: Path) -> None:
        """**반례** — 트리가 더러워도 *그 경로*가 깨끗하면 통과한다.

        이 절이 없으면 "트리가 더러우면 전부 막는다"는 구현이 통과한다. 탐지 기준이
        경로 단위임을 재는 유일한 픽스처다.
        """
        _dirty(repo)
        result = _run("git checkout -- keep.txt", repo)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout -b feature/new",
            "git checkout -B feature/new main",
            "git stash pop",
            "git stash list",
            "git stash show",
        ],
    )
    def test_exempt_commands_pass_even_on_a_dirty_tree(self, repo: Path, command: str) -> None:
        """**면제 절의 반례** — 트리가 *더러운* 상태에서 재야 면제가 실제로 밟힌다.

        깨끗한 트리에서는 면제가 없어도 통과하므로(잃을 것이 0건), 위 정상 묶음은
        `-b` 면제·안전 stash 면제 절을 한 번도 지나가지 않는다. 뮤테이션 M6·M7이
        살아남아 그 사실을 드러냈다 — 절을 지울 일이 아니라 픽스처를 고칠 일이다.

        의미: 브랜치 생성은 경로를 되돌리지 않고, `stash pop|list|show` 는 잃는
        동작이 아니라 되살리거나 조회하는 동작이다. 더러운 트리에서 이것들을 막으면
        정상 워크플로가 통째로 깨진다.
        """
        _dirty(repo)
        result = _run(command, repo)
        assert (
            result.returncode == 0
        ), f"더러운 트리에서 면제 명령을 막았다: {command}\n{result.stderr}"

    def test_branch_creation_passes_even_when_branch_name_collides_with_dirty_path(
        self, repo: Path
    ) -> None:
        """**`-b` 면제 절의 진짜 반례** — 브랜치명이 더러운 *경로*와 같을 때.

        바로 위 테스트로는 이 절이 밟히지 않는다(뮤테이션 M6 생존이 그것을 드러냈다):
        `git checkout -b feature/new` 는 면제가 없어도 통과한다 — 남은 인자
        `feature/new` 를 pathspec 으로 조회하면 그런 경로가 없어 "변경 0건"이 나오기
        때문이다. 즉 절이 관대한 게 아니라 픽스처가 그 자리를 지나가지 않았다.

        면제가 실제로 일하는 순간은 **이름이 충돌할 때**다. `backlog/` 가 더러운
        상태에서 `git checkout -b backlog` 를 내면, 면제가 없으면 pathspec 조회가
        그 디렉터리의 변경을 집어 **브랜치 생성을 오차단한다**. 브랜치 생성은 어떤
        경로도 되돌리지 않으므로 그것은 순수 오탐이다.
        """
        _dirty(repo)
        result = _run("git checkout -b backlog", repo)
        assert result.returncode == 0, (
            "브랜치명이 더러운 경로와 같다고 브랜치 생성을 막았다 — 순수 오탐\n" + result.stderr
        )

    def test_safe_stash_action_passes_even_when_its_name_collides_with_a_dirty_path(
        self, repo: Path
    ) -> None:
        """**안전 stash 면제 절의 진짜 반례** — 서브커맨드명과 같은 경로가 더러울 때.

        위와 같은 기전이다(뮤테이션 M7 생존). `git stash pop` 은 면제가 없어도
        통과하는데, 남은 인자 `pop` 을 pathspec 으로 조회하면 그런 경로가 없기
        때문이다. 이름이 충돌하면 그 우연이 깨진다 — 그때 면제 절만이 오차단을 막는다.

        `stash pop` 은 스태시를 **되살리는** 동작이라 잃을 것이 없다. 되살리기를
        막으면 사고 복구 경로 자체가 닫힌다.
        """
        (repo / "pop").write_text("원본\n", encoding="utf-8")
        _git("add", "pop", cwd=repo)
        _git("commit", "-m", "add pop", cwd=repo)
        (repo / "pop").write_text("고침\n", encoding="utf-8")
        result = _run("git stash pop", repo)
        assert result.returncode == 0, (
            "되살리기 동작을 이름 충돌 때문에 막았다 — 복구 경로가 닫힌다\n" + result.stderr
        )

    def test_staged_only_restore_is_not_worktree_loss(self, repo: Path) -> None:
        """`restore --staged` 는 인덱스만 되돌린다 — 작업 트리 손실이 아니다."""
        _dirty(repo)
        _git("add", "backlog/events.ndjson", cwd=repo)
        assert _run("git restore --staged backlog/events.ndjson", repo).returncode == 0


class TestBlocksWhenThereIsSomethingToLose:
    """② 위반에서 실제로 막는다."""

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout -- backlog/events.ndjson",
            "git checkout -- backlog/",
            "git checkout .",
            "git restore backlog/events.ndjson",
            "git restore --worktree --staged backlog/events.ndjson",
            "git stash",
            "git stash push backlog/events.ndjson",
            "git -C . checkout -- backlog/events.ndjson",  # 전역 옵션 뒤의 서브커맨드
            "git add keep.txt && git checkout -- backlog/events.ndjson",  # 체인 뒷단
        ],
    )
    def test_dirty_path_is_blocked(self, repo: Path, command: str) -> None:
        _dirty(repo)
        result = _run(command, repo)
        assert result.returncode == 2, f"막지 못했다: {command}"
        assert "git_revert_guard" in result.stderr
        assert "무증상" in result.stderr, "왜 위험한지 말하지 않으면 사람이 판단할 수 없다"

    def test_message_names_the_alternative(self, repo: Path) -> None:
        """차단만 하고 대안을 안 주면 사람은 가드를 우회한다."""
        _dirty(repo)
        err = _run("git checkout -- backlog/events.ndjson", repo).stderr
        assert "cp" in err, "cp 백업 경유라는 대안이 메시지에 없다"
        assert guard.ESCAPE_MARKERS[0] in err, "탈출구를 안 알려주면 우회 경로를 스스로 만든다"

    def test_stash_drop_blocked_only_when_stash_is_nonempty(self, repo: Path) -> None:
        """스태시 축의 양방향 — 비어 있으면 통과, 들어 있으면 차단."""
        assert _run("git stash drop", repo).returncode == 0, "빈 스태시를 막았다"
        _dirty(repo)
        _git("stash", cwd=repo)
        assert _run("git stash drop", repo).returncode == 2
        assert _run("git stash clear", repo).returncode == 2


class TestUnknownIsNotTreatedAsSafe:
    """모른다 ≠ 아니다 — 판정 불가를 '잃을 것 없음'으로 접지 않는다."""

    def test_unparseable_revert_command_is_blocked(self, repo: Path) -> None:
        result = _run('git checkout -- "unbalanced', repo)
        assert result.returncode == 2
        assert "파싱하지 못했다" in result.stderr

    def test_unparseable_unrelated_command_passes(self, repo: Path) -> None:
        """**반례** — 파싱 실패만으로는 막지 않는다. 원복 낱말이 있어야 한다.

        이 절이 없으면 "따옴표가 안 맞으면 전부 막는다"는 구현이 통과하고, 그러면
        가드가 무관한 명령에서 상시 발화한다.
        """
        assert _run('echo "unbalanced', repo).returncode == 0

    def test_status_lookup_failure_blocks_and_says_so(self, tmp_path: Path) -> None:
        """**조회 실패 절의 반례** — git 저장소가 아닌 곳에서 원복 명령을 낸다.

        `git status` 가 비-0으로 끝나 "잃을 것이 있는가"를 판정할 수 없다. 그때
        통과시키면 *조회 실패가 곧 안전*이라는 뜻이 되는데, 이 명령은 실제로
        파괴적이므로 그 등식은 성립하지 않는다(모른다 ≠ 아니다).

        이 픽스처가 없으면 뮤테이션 M3(조회 실패를 '없음'으로 접기)이 살아남는다 —
        다른 테스트는 전부 정상 저장소를 쓰므로 그 분기를 한 번도 밟지 않는다.
        """
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        result = _run("git checkout -- something.txt", plain)
        assert result.returncode == 2, "판정 불가를 통과로 접었다"
        assert "판정하지 못했다" in result.stderr

    def test_non_bash_tool_is_ignored(self, repo: Path) -> None:
        payload = {"tool_name": "Read", "tool_input": {"file_path": "x"}, "cwd": str(repo)}
        result = subprocess.run(
            [sys.executable, str(_GUARD)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0

    def test_malformed_input_passes_but_names_the_exception(self, repo: Path) -> None:
        """관측 실패가 작업 실패가 되면 안 된다 — 다만 무타입 침묵은 금지다."""
        result = subprocess.run(
            [sys.executable, str(_GUARD)],
            input="not json",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "JSONDecodeError" in result.stderr


class TestEscapeHatchIsRecorded:
    """탈출구는 있되 남는다 — 남지 않는 탈출구는 게이트를 끄는 것과 같다."""

    def test_escape_marker_allows_and_logs(self, repo: Path, monkeypatch) -> None:
        _dirty(repo)
        logs = repo / ".claude" / "logs"
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        payload = {
            "tool_name": "Bash",
            "tool_input": {
                "command": f"git checkout -- backlog/events.ndjson  {guard.ESCAPE_MARKERS[0]}"
            },
            "cwd": str(repo),
            "session_id": "test",
        }
        result = subprocess.run(
            [sys.executable, str(_GUARD)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=60,
            env={**__import__("os").environ, "CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0
        rows = [
            json.loads(line)
            for line in (logs / "git_revert_blocks.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert rows and rows[-1]["escaped"] is True
        assert rows[-1]["blocked"] is False
