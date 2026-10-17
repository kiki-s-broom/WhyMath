"""HARN-49 — Stop 훅의 대장 무결성 게이트: 내 위반을 안고 세션을 끝내지 못하게.

**사고 (2026-08-31 실측)**: `validate`가 "1세션이 2개 태스크 동시 claim" 위반을
정확히 냈는데, 명령을 `;`로 이어 붙여 **exit code를 판정에 쓰지 않은 채 push**했다.
2선 방어인 CI `harness-integrity` 잡은 그 push에 **트리거가 걸리지 않아**(HARN-30)
무증상이었다. 규칙(CLAUDE.md 2026-08-09 "검사 명령의 출력을 억제하거나 잘라서 판정
금지")은 **이미 있었고 재발했다** — 규칙이 아니라 코드로 옮기는 이유다.

이 파일이 동결하는 것:
  ① 실사고 재현 — 한 세션이 2태스크를 claim한 상태로 정지하면 **exit 2로 막힌다**
  ② **볼모 방지(변별력의 반대 방향)** — *남의* 위반으로는 막지 않는다.
     저장소 전역 위반에 모든 세션이 걸리면 그 훅은 곧 무력화된다.
  ③ 정상 상태는 통과 — 훅이 개발을 막지 않는다
  ④ stop_hook_active 재정지는 즉시 통과(무한 루프 방지, 기존 계약 유지)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import store
from _hook_stdin import set_hook_stdin

import backlog as cli


@pytest.fixture
def seeded(git_repo: Path, monkeypatch) -> Path:
    """세션 브랜치 위의 시드 저장소.

    **브랜치를 만드는 것이 필수다** — check-stop은 `branch in ("unknown","main","")`
    이면 즉시 통과한다(메인에서의 임시 작업을 볼모로 잡지 않기 위한 기존 계약).
    main에서 테스트하면 게이트에 도달조차 못 해 **전건이 공허하게 통과**한다.
    """
    subprocess.run(
        ["git", "checkout", "-b", "claude/harn49-test"],
        cwd=git_repo,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    assert (
        store.current_branch(git_repo) == "claude/harn49-test"
    ), "픽스처가 세션 브랜치를 못 만들었다"
    return git_repo


def _add(task_id: str) -> int:
    return cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--title",
            "HARN-49 테스트",
            "--track",
            "math-completion",
            "--stage",
            "S1",
        ]
    )


def _check_stop(monkeypatch, payload: dict | None = None) -> int:
    set_hook_stdin(monkeypatch, json.dumps(payload or {}))
    return cli.main(["check-stop"])


class TestIncidentReproduction:
    """① 실사고 — 1세션 2태스크 claim 상태로는 정지할 수 없다."""

    def test_two_claims_blocks_stop(self, seeded: Path, monkeypatch):
        assert _add("T1-01-first") == 0
        assert _add("T1-02-second") == 0
        assert cli.main(["start", "T1-01-first", "--no-remote"]) == 0
        assert cli.main(["start", "T1-02-second", "--no-remote"]) == 0
        # 이 상태가 정확히 2026-08-31에 push된 상태다
        assert [e for e in store.validate_backlog(store.load_backlog(seeded)[0])], "전제 확인"
        assert _check_stop(monkeypatch) == 2, "위반을 안고 세션이 끝났다 — 사고 재현"

    def test_resolving_the_violation_unblocks(self, seeded: Path, monkeypatch):
        """해소하면 풀린다 — 영구 차단이 아니어야 한다."""
        assert _add("T1-03-a") == 0
        assert _add("T1-04-b") == 0
        assert cli.main(["start", "T1-03-a", "--no-remote"]) == 0
        assert cli.main(["start", "T1-04-b", "--no-remote"]) == 0
        assert _check_stop(monkeypatch) == 2
        assert cli.main(["done", "T1-03-a", "--artifact", "PR #1 테스트 증적"]) == 0
        assert _check_stop(monkeypatch) != 2, "해소했는데도 막히면 훅이 볼모를 잡는다"


class TestNoHostageTaking:
    """② 변별력의 반대 방향 — 남의 위반으로는 막지 않는다."""

    def test_other_session_violation_does_not_block(self, seeded: Path, monkeypatch):
        """다른 브랜치가 남긴 위반은 이 세션의 정지를 막지 않는다.

        이 축이 없으면 main에 위반이 하나 있을 때 **모든 세션의 정지가 막히고**,
        그러면 훅은 즉시 무력화(우회·비활성화)된다. 한 방향만 검증하면 그 결함을
        못 잡는다.
        """
        assert _add("T1-05-foreign-a") == 0
        assert _add("T1-06-foreign-b") == 0
        backlog, _ = store.load_backlog(seeded)
        for tid in ("T1-05-foreign-a", "T1-06-foreign-b"):
            task = backlog.tasks[tid]
            task.status = "in_progress"
            task.session = "claude/someone-else"  # 남의 세션이 2건 claim
            store.save_task(seeded, task)
        # 전역 validate는 위반을 낸다
        assert [e for e in store.validate_backlog(store.load_backlog(seeded)[0])], "전제 확인"
        # 그러나 이 세션은 그 위반의 당사자가 아니므로 정지가 막히지 않는다
        assert _check_stop(monkeypatch) != 2


class TestCleanStatePasses:
    """③④ 정상 상태·재정지는 통과 — 훅이 개발을 볼모로 잡지 않는다."""

    def test_clean_ledger_passes(self, seeded: Path, monkeypatch):
        assert _check_stop(monkeypatch) == 0

    def test_single_claim_without_commits_passes(self, seeded: Path, monkeypatch):
        assert _add("T1-07-single") == 0
        assert cli.main(["start", "T1-07-single", "--no-remote"]) == 0
        assert _check_stop(monkeypatch) != 2

    def test_stop_hook_active_short_circuits(self, seeded: Path, monkeypatch):
        """무한 루프 방지 계약 유지 — 위반이 있어도 재정지는 통과."""
        assert _add("T1-08-x") == 0
        assert _add("T1-09-y") == 0
        assert cli.main(["start", "T1-08-x", "--no-remote"]) == 0
        assert cli.main(["start", "T1-09-y", "--no-remote"]) == 0
        assert _check_stop(monkeypatch, {"stop_hook_active": True}) == 0
