"""`done --no-pr direct-commit` 의 trunk 조상 실측 (HARN-80).

CUR-07처럼 PR 없이 main에 직접 착지한 산출물은 기존 예외 4종 어느 것으로도 done 할 수 없었다.
새 사유는 "이미 main에 들어갔다"는 *검증 가능한* 주장이므로, 신고가 아니라 git 실측으로 받는다.

양방향 + 3상태로 본다: 조상이면 성공(오탐 없음), 비조상이면 exit 1(변별력), 측정 불가면
exit 3(0건 통과 위장 금지). 조상 검사 자체를 지우는 뮤테이션은 이 파일이 RED를 내야 한다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import remote_claims
import store

import backlog as cli


def _git(repo: Path, *argv: str) -> str:
    result = subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def landed_repo(git_repo: Path, tmp_path_factory, monkeypatch) -> Path:
    """origin(bare)을 가진 저장소 — main은 push·fetch 완료라 `origin/main`이 존재한다."""
    bare = tmp_path_factory.mktemp("origin") / "origin.git"
    bare.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "-b", "main"], cwd=bare, check=True, capture_output=True
    )
    _git(git_repo, "remote", "add", "origin", str(bare))
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "seed ledger")
    _git(git_repo, "push", "origin", "main")
    _git(git_repo, "fetch", "origin", "main")
    return git_repo


def _claimed_task(capsys) -> str:
    assert cli.main(["next", "--n", "1", "--json"]) == 0
    task_id = json.loads(capsys.readouterr().out)[0]["id"]
    assert cli.main(["start", task_id, "--session", "test-branch"]) == 0
    capsys.readouterr()
    return task_id


def _events(repo: Path) -> list[dict]:
    text = "".join(p.read_text(encoding="utf-8") for p in store.event_paths(repo))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _status(repo: Path, task_id: str) -> str:
    backlog, _ = store.load_backlog(repo)
    return backlog.tasks[task_id].status


class TestAncestorLands:
    def test_trunk_ancestor_sha_allows_done(self, landed_repo: Path, capsys):
        """main 조상 sha로는 PR 없이 done 성공"""
        task_id = _claimed_task(capsys)
        sha = _git(landed_repo, "rev-parse", "HEAD")
        rc = cli.main(
            [
                "done",
                task_id,
                "--artifact",
                sha[:8],
                "--no-pr",
                "direct-commit",
                "--direct-commit-sha",
                sha[:8],
            ]
        )
        assert rc == 0
        assert _status(landed_repo, task_id) == "done"

    def test_note_and_event_record_full_sha(self, landed_repo: Path, capsys):
        """사유·sha가 notes와 이벤트 양쪽에 남는다 — 남지 않는 탈출구는 게이트를 끄는 것"""
        task_id = _claimed_task(capsys)
        sha = _git(landed_repo, "rev-parse", "HEAD")
        assert (
            cli.main(
                [
                    "done",
                    task_id,
                    "--artifact",
                    sha,
                    "--no-pr",
                    "direct-commit",
                    "--direct-commit-sha",
                    sha[:10],
                ]
            )
            == 0
        )
        backlog, _ = store.load_backlog(landed_repo)
        notes = backlog.tasks[task_id].notes
        assert "직접 커밋 착지" in notes and sha in notes
        # '보류'가 아니므로 HARN-57 사후 해소 로직이 오인하지 않는다
        assert "PR 보류" not in notes
        done = [
            e for e in _events(landed_repo) if e.get("id") == task_id and e.get("action") == "done"
        ]
        assert done[-1]["no_pr_reason"] == "direct-commit"
        assert done[-1]["direct_commit_sha"] == sha


class TestNonAncestorRejected:
    def test_branch_only_commit_rejected(self, landed_repo: Path, capsys):
        """브랜치 전용(push 안 된) 커밋은 exit 1, 대장은 그대로"""
        task_id = _claimed_task(capsys)
        _git(landed_repo, "checkout", "-b", "side")
        (landed_repo / "side.txt").write_text("x\n", encoding="utf-8")
        _git(landed_repo, "add", "side.txt")
        _git(landed_repo, "commit", "-m", "side only")
        sha = _git(landed_repo, "rev-parse", "HEAD")
        rc = cli.main(
            [
                "done",
                task_id,
                "--artifact",
                sha,
                "--no-pr",
                "direct-commit",
                "--direct-commit-sha",
                sha,
            ]
        )
        assert rc == 1
        assert "조상이 아니다" in capsys.readouterr().err
        assert _status(landed_repo, task_id) == "in_progress"  # 반쪽 적용 금지
        assert not [
            e for e in _events(landed_repo) if e.get("action") == "done" and e.get("id") == task_id
        ]


class TestUnmeasurableIsNotAPass:
    def test_shallow_clone_exits_3(self, landed_repo: Path, capsys, monkeypatch):
        """shallow면 측정 불가 — exit 3, 통과 아님"""
        task_id = _claimed_task(capsys)
        sha = _git(landed_repo, "rev-parse", "HEAD")
        real = remote_claims._git

        def fake(root, *argv, **kw):
            if argv[:2] == ("rev-parse", "--is-shallow-repository"):
                return subprocess.CompletedProcess(argv, 0, stdout="true\n", stderr="")
            return real(root, *argv, **kw)

        monkeypatch.setattr(remote_claims, "_git", fake)
        rc = cli.main(
            [
                "done",
                task_id,
                "--artifact",
                sha,
                "--no-pr",
                "direct-commit",
                "--direct-commit-sha",
                sha,
            ]
        )
        assert rc == 3
        assert "shallow" in capsys.readouterr().err
        assert _status(landed_repo, task_id) == "in_progress"

    def test_git_exception_exits_3_with_type_name(self, landed_repo: Path, capsys, monkeypatch):
        """git 실행 예외도 측정 불가 — 예외 타입명이 남는다(침묵 실패 금지)"""
        task_id = _claimed_task(capsys)
        sha = _git(landed_repo, "rev-parse", "HEAD")

        def boom(root, *argv, **kw):
            raise subprocess.TimeoutExpired(cmd="git", timeout=1)

        monkeypatch.setattr(remote_claims, "_git", boom)
        rc = cli.main(
            [
                "done",
                task_id,
                "--artifact",
                sha,
                "--no-pr",
                "direct-commit",
                "--direct-commit-sha",
                sha,
            ]
        )
        assert rc == 3
        assert "TimeoutExpired" in capsys.readouterr().err
        assert _status(landed_repo, task_id) == "in_progress"

    def test_unknown_sha_exits_3(self, landed_repo: Path, capsys):
        """이 클론에 없는 해시 — 존재 여부를 모르므로 통과시키지 않는다"""
        task_id = _claimed_task(capsys)
        fake_sha = "deadbeef" * 5
        rc = cli.main(
            [
                "done",
                task_id,
                "--artifact",
                fake_sha,
                "--no-pr",
                "direct-commit",
                "--direct-commit-sha",
                fake_sha,
            ]
        )
        assert rc == 3
        assert _status(landed_repo, task_id) == "in_progress"

    def test_missing_origin_main_exits_3(self, git_repo: Path, monkeypatch, capsys):
        """origin/main 이 없는 저장소 — 조상 판정 기준 부재는 측정 불가"""
        monkeypatch.chdir(git_repo)
        assert cli.main(["seed"]) == 0
        capsys.readouterr()  # seed 출력이 next --json 파싱을 오염시키지 않게 비운다
        task_id = _claimed_task(capsys)
        sha = _git(git_repo, "rev-parse", "HEAD")
        rc = cli.main(
            [
                "done",
                task_id,
                "--artifact",
                sha,
                "--no-pr",
                "direct-commit",
                "--direct-commit-sha",
                sha,
            ]
        )
        assert rc == 3


class TestArgumentContract:
    def test_direct_commit_without_sha_rejected(self, landed_repo: Path, capsys):
        """sha 없이 direct-commit은 거부"""
        task_id = _claimed_task(capsys)
        assert cli.main(["done", task_id, "--artifact", "abc1234", "--no-pr", "direct-commit"]) == 1
        assert _status(landed_repo, task_id) == "in_progress"

    @pytest.mark.parametrize("bad", ["--upload-pack=x", "zzzzzzz", "abc", "HEAD"])
    def test_malformed_sha_rejected(self, landed_repo: Path, capsys, bad: str):
        """옵션 주입·비16진·너무 짧은 값·심볼릭 ref는 git에 닿기 전에 거부"""
        task_id = _claimed_task(capsys)
        # `=` 결합 형태로 넘겨야 '-'로 시작하는 값이 argparse 옵션으로 오인되지 않고 우리 검증에 닿는다
        rc = cli.main(
            [
                "done",
                task_id,
                "--artifact",
                "abc1234",
                "--no-pr",
                "direct-commit",
                f"--direct-commit-sha={bad}",
            ]
        )
        assert rc == 1
        assert _status(landed_repo, task_id) == "in_progress"

    def test_sha_flag_without_direct_commit_rejected(self, landed_repo: Path, capsys):
        """다른 사유에 sha를 얹어 검증을 우회·혼동하지 못한다"""
        task_id = _claimed_task(capsys)
        rc = cli.main(
            [
                "done",
                task_id,
                "--artifact",
                "abc1234",
                "--no-pr",
                "kiki-hold",
                "--direct-commit-sha",
                "abc1234",
            ]
        )
        assert rc == 1
        assert _status(landed_repo, task_id) == "in_progress"


class TestExistingReasonsUnchanged:
    @pytest.mark.parametrize("reason", ["investigation", "incomplete", "ci-red", "kiki-hold"])
    def test_legacy_reasons_still_pass_without_git_probe(
        self, landed_repo: Path, capsys, monkeypatch, reason
    ):
        """기존 4종은 git 조상 검사를 타지 않고 종전대로 통과, 'PR 보류' 태그를 남긴다"""

        def forbidden(*_a, **_k):
            raise AssertionError("기존 --no-pr 4종이 trunk 조상 검사를 호출했다")

        monkeypatch.setattr(cli, "_probe_trunk_landing", forbidden)
        task_id = _claimed_task(capsys)
        assert cli.main(["done", task_id, "--artifact", "abc123", "--no-pr", reason]) == 0
        backlog, _ = store.load_backlog(landed_repo)
        assert "PR 보류" in backlog.tasks[task_id].notes
