"""EOS-210 런북 [G] 커밋 블록의 형태 동결 (리뷰 P2-2·P2-3).

`check_runbook_blocks.py`는 "쓰기가 가드 안에 있는가"를 보지만, 아래 두 사고는 그 가드 **안에서**
일어난다 — 그래서 이 런북의 커밋 블록 형태를 따로 고정한다.

  P2-2 공유 클론에서 `git commit`이 인덱스 전체를 커밋한다 → 다른 세션의 스테이징까지 push된다.
       대책: 시작 전 `git diff --cached --quiet`(스테이징 0) + 커밋에 두 경로만 지정.
  P2-3 PowerShell `;`는 앞 명령이 실패해도 다음을 실행한다 → `git switch -c`가 "이미 있음"으로
       실패하면 커밋이 현재 브랜치(main)에 들어간다.
       대책: 브랜치 부재(로컬·원격)를 가드 조건에 넣고, 단계마다 `$LASTEXITCODE`를 확인.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO / "docs" / "ops" / "eos210_hint_human_verdict_runbook.md"
_FENCE = re.compile(r"```powershell\n(.*?)```", re.DOTALL)


def _commit_block() -> str:
    blocks = [b for b in _FENCE.findall(_RUNBOOK.read_text(encoding="utf-8")) if "git commit" in b]
    assert len(blocks) == 1, f"git commit 블록이 {len(blocks)}개 — 1개여야 한다"
    return blocks[0]


def _line_with(block: str, token: str) -> str:
    lines = [line for line in block.splitlines() if token in line]
    assert len(lines) == 1, f"{token!r} 줄이 {len(lines)}개"
    return lines[0]


def test_nothing_staged_is_part_of_the_write_guard() -> None:
    block = _commit_block()
    assert "git diff --cached --quiet" in block
    guard = _line_with(block, "$CommitReady = ")
    assert "$NothingStaged" in guard


def test_commit_names_only_the_two_record_files() -> None:
    commit = _line_with(_commit_block(), "git commit")
    assert re.search(r"git commit -m \"[^\"]+\" -- \$Manifest \$Verdicts;", commit), commit


def test_branch_must_be_absent_locally_and_remotely() -> None:
    block = _commit_block()
    assert "git rev-parse --verify --quiet" in block and "git ls-remote --exit-code" in block
    assert "$BranchFree" in _line_with(block, "$CommitReady = ")


def test_each_write_step_runs_only_after_the_previous_succeeded() -> None:
    """switch 뒤의 add·commit·push는 전부 `if ($Rc -eq 0)` 안에 있어야 한다(`;` 연쇄 금지)."""
    block = _commit_block()
    for token in ("git add --", "git commit", "git push"):
        line = _line_with(block, token)
        assert line.lstrip().startswith("if ($Rc -eq 0) {"), line
    switch = _line_with(block, "git switch -c")
    assert "$Rc = $LASTEXITCODE" in switch


def test_clone_is_returned_only_if_the_switch_happened() -> None:
    block = _commit_block()
    returns = [line for line in block.splitlines() if "git switch $OrigBranch" in line]
    assert returns and all("$Switched" in line for line in returns)


def test_records_are_restored_to_the_worktree_after_switching_back() -> None:
    """확인 리뷰 P2-2 — 원래 브랜치(main)에서 두 파일은 미추적이라 `git switch`가 작업 트리에서
    지운다. 돌아간 *뒤에* 커밋본을 작업 트리에만 복원하고(인덱스 무변경), 내용이 커밋본과 같은지
    blob 해시로 확인해야 한다."""
    block = _commit_block()
    lines = block.splitlines()
    restore = _line_with(block, "git restore")
    assert "git restore --source=$Branch --worktree -- $Manifest $Verdicts" in restore
    assert restore.lstrip().startswith("if ($Committed) {"), restore
    assert "--staged" not in restore
    assert "git hash-object $Manifest" in restore and "git hash-object $Verdicts" in restore
    switch_back = max(i for i, line in enumerate(lines) if "git switch $OrigBranch" in line)
    assert lines.index(restore) > switch_back, "복원은 원래 브랜치로 돌아간 뒤여야 한다"
    commit = _line_with(block, "git commit")
    assert "$Committed = ($Rc -eq 0)" in commit
