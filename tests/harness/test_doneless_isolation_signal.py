"""HARN-31 — done 표기 없는 고립 브랜치의 구현 신호.

사고(2026-08-11 감사 §4-1): `claude/whymath-pedagogy-review-gdmwhk`는 구현 파일 수십 개를 쌓아 두고
태스크를 `todo`로 남겼다. "브랜치 done vs main done" 대조(`scan_remote_done`·stray-code ②)는 done
표기를 전제하므로 **0건**이었고, 스캔은 그 브랜치를 문서 전용 브랜치와 똑같은 한 줄로만 보였다.

변별력의 핵심은 양방향이다 — 구현이 있는 브랜치와 문서 전용 브랜치가 **다른 값**을 내야 하고,
측정 실패(`None`)는 "구현 없음"(`0`)과 **다른 값**이어야 한다. 한 방향만 검사하면 "항상 0" 또는
"항상 양수"인 구현도 통과한다.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import remote_claims
import report

import backlog as cli


def _git(repo: Path, *argv: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *argv],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
    )


def _commit(repo: Path, files: dict[str, str], message: str, *, days_ago: int = 9) -> None:
    """`days_ago`일 전 시각으로 파일들을 한 커밋에 담는다(나이 임계 통과용)."""
    for name, body in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        _git(repo, "add", name)
    iso = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    _git(repo, "commit", "-m", message, env={"GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso})


def _push_branch(repo: Path, branch: str, files: dict[str, str]) -> None:
    _git(repo, "checkout", "main")
    _git(repo, "checkout", "-b", branch)
    _commit(repo, files, f"{branch} work")
    _git(repo, "push", "-u", "origin", branch)


def _entry(root: Path, branch: str, **kwargs) -> remote_claims.StaleBranch:
    result = remote_claims.scan_stale_branches(root, days_threshold=3, **kwargs)
    assert result.status == "ok"
    return {s.branch: s for s in result.stale}[branch]


class TestImplSignalScan:
    def test_code_branch_without_done_marker_is_visible(self, bare_remote):
        """done_표기_없는_구현_브랜치도_구현_신호가_양수다 (gdmwhk 형태 재현)

        브랜치는 태스크를 `todo`로 둔 채 src·tests·data 신규 파일을 쌓았다. 옛 대조는 이 브랜치를
        못 내고(`scan_remote_done` → `{}`), 신규 신호만이 그것을 드러낸다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-pedagogy-review-gdmwhk"
        _push_branch(
            a,
            branch,
            {
                "backlog/tasks/PED-18-x.yaml": "id: PED-18-x\nstatus: todo\n",
                "src/strategy.py": "x = 1\n",
                "tests/test_strategy.py": "def test_x():\n    pass\n",
                "data/corpus/s1.yaml": "k: v\n",
            },
        )

        # ① 재현 고정 — 옛 done 대조는 이 브랜치를 못 본다(그래서 이 태스크가 존재한다).
        found, status = remote_claims.scan_remote_done(b, ["PED-18-x"], fetch=True)
        assert status == "ok"
        assert found == {}, "done 표기가 없으므로 done 대조는 0건이다 — 이것이 사각이다"

        # ② 신호 — 신규 3파일(원장 backlog/ 는 제외)
        entry = _entry(b, branch)
        assert entry.status == "isolated"
        assert entry.impl_new == 3
        assert entry.impl_changed == 0
        assert entry.impl_scan_error == ""

    def test_doc_only_branch_has_no_impl_signal(self, bare_remote):
        """문서_전용_브랜치는_구현_신호가_0이다 (양방향 변별의 반대쪽)

        위 테스트만 있으면 "항상 양수"인 구현도 통과한다. 0과 양수가 다른 값을 내야 변별력이 있다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-data-platform-design-t608mk"
        _push_branch(
            a,
            branch,
            {
                "docs/architecture/review.md": "문서\n",
                "MEMORY.md": "기록\n",
                "backlog/x.yaml": "a: 1\n",
            },
        )

        entry = _entry(b, branch)
        assert (entry.impl_new, entry.impl_changed) == (0, 0)
        assert entry.impl_scan_error == ""

    def test_modification_only_branch_is_not_hidden(self, bare_remote):
        """기존_파일만_고친_브랜치도_신호가_보인다 (신규만 세면 숨는다)

        기존 모듈을 고쳐 끝낸 작업(감사 A5·A6: `api/speech.py`·`models.py` 변경만)은 신규 0이다.
        신규만 세면 이것이 문서 전용과 같은 화면이 된다 — 과소보고 금지(#785).
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _git(a, "checkout", "main")
        _commit(a, {"src/module.py": "v = 1\n"}, "main: 모듈 추가", days_ago=20)
        _git(a, "push", "origin", "main")
        branch = "claude/whymath-coding-architecture-iws58k"
        _git(a, "checkout", "-b", branch)
        _commit(a, {"src/module.py": "v = 2\n"}, "수정만")
        _git(a, "push", "-u", "origin", branch)

        entry = _entry(b, branch)
        assert (entry.impl_new, entry.impl_changed) == (0, 1)

    def test_rename_counts_as_changed_by_current_path(self, bare_remote):
        """이름_변경은_현재_경로_기준으로_수정에_센다

        `R100\\t옛\\t새` 형태는 필드가 3개다. 마지막 필드(현재 경로)를 쓰지 않고 두 번째를 쓰면
        옛 경로의 최상위를 판정해 원장 취급으로 버릴 수 있다 — 여기서는 docs→src 이동으로 검증한다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _git(a, "checkout", "main")
        _commit(a, {"docs/moved.py": "same = 1\n"}, "main: 문서 위치 파일", days_ago=20)
        _git(a, "push", "origin", "main")
        branch = "claude/whymath-rename-branch-abc123"
        _git(a, "checkout", "-b", branch)
        (a / "src").mkdir()
        _git(a, "mv", "docs/moved.py", "src/moved.py")
        iso = (datetime.now(timezone.utc) - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        _git(a, "commit", "-m", "이동", env={"GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso})
        _git(a, "push", "-u", "origin", branch)

        entry = _entry(b, branch)
        assert (entry.impl_new, entry.impl_changed) == (0, 1), "현재 경로(src/)로 판정해야 한다"

    def test_measurement_failure_is_indeterminate_not_zero(self, bare_remote, monkeypatch):
        """측정_실패는_0이_아니라_판정_불가다 (모른다 ≠ 구현 없음)

        git이 잠깐 실패한 것을 `0`으로 읽으면 구현이 든 브랜치가 문서 전용과 같은 줄이 된다 —
        측정 실패가 통과로 위장된다. `None` + 사유(예외 타입명 포함)여야 한다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-flaky-measure-def456"
        _push_branch(a, branch, {"src/x.py": "x\n"})

        real_git = remote_claims._git

        def flaky(root, *argv, **kwargs):
            if argv[:2] == ("diff", "--name-status"):
                raise TimeoutError("git diff 타임아웃(합성)")
            return real_git(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", flaky)
        entry = _entry(b, branch)

        assert entry.impl_new is None and entry.impl_changed is None
        assert "TimeoutError" in entry.impl_scan_error  # 침묵 실패 금지 — 타입명이 남는다

    def test_git_nonzero_exit_is_indeterminate_not_zero(self, bare_remote, monkeypatch):
        """git_비0_종료도_0이_아니라_판정_불가다 (예외 경로와 별개의 분기)

        위 테스트는 *예외*가 터지는 길만 밟는다. `git diff`가 예외 없이 종료코드 128로 끝나는 길
        (잘린 히스토리·병합 기준 부재)은 다른 분기이고, 거기서 `(0, 0)`을 돌려주면 같은 위장이
        생긴다 — 이 분기를 지우는 뮤테이션이 살아남아 발견됐다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-nonzero-exit-jkl012"
        _push_branch(a, branch, {"src/z.py": "z\n"})

        real_git = remote_claims._git

        def failing(root, *argv, **kwargs):
            if argv[:2] == ("diff", "--name-status"):
                return subprocess.CompletedProcess(argv, 128, "", "fatal: no merge base")
            return real_git(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", failing)
        entry = _entry(b, branch)

        assert entry.impl_new is None and entry.impl_changed is None
        assert "git diff exit 128" in entry.impl_scan_error

    def test_non_decision_statuses_are_not_measured(self, bare_remote):
        """처분_경로가_있는_분류는_측정하지_않는다 (active는 None 그대로)

        active(타 세션 진행)는 방치가 아니라 정상 작업이므로 구현 신호로 경고할 대상이 아니다.
        측정 안 함(None)과 구현 없음(0)을 구분해 두는 이유이기도 하다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-active-work-ghi789"
        _push_branch(a, branch, {"src/y.py": "y\n"})

        entry = _entry(b, branch, active_branches=frozenset({branch}))

        assert entry.status == "active"
        assert entry.impl_new is None and entry.impl_changed is None
        assert entry.impl_scan_error == ""


class TestImplSignalRender:
    """브리핑 노출 — 3상태가 서로 다른 문장으로 나가는가."""

    def test_three_states_render_distinct_lines(self):
        positive = report.impl_signal_line(16, 5)
        zero = report.impl_signal_line(0, 0)
        failed = report.impl_signal_line(None, None, "TimeoutError: x")
        unmeasured = report.impl_signal_line(None, None, "")

        assert "신규 16파일" in positive and "수정 5파일" in positive
        assert "구현 신호 없음" in zero
        assert "판정 불가" in failed and "TimeoutError" in failed
        assert unmeasured == ""  # 미측정은 말하지 않는다 — 0이라고 거짓말하지도 않는다
        assert len({positive, zero, failed}) == 3

    def test_modification_only_is_positive_not_zero(self):
        """수정만 있어도 양수 문장이다 — 합산이 아니라 `신규+수정 > 0` 판정."""
        assert "구현 신호 없음" not in report.impl_signal_line(0, 1)

    def test_brief_exposes_signal_under_isolated_branch(self):
        """brief가_고립_브랜치_바로_아래에_구현_신호를_실제로_출력한다 (배선 확인)

        신호를 계산해 두고 렌더가 안 부르면 "있지만 아무도 못 보는" 상태다(CLAUDE.md 정본화≠집행).
        """
        from datetime import date

        from models import Backlog

        text = report.render_brief(
            Backlog(tasks={}),
            [],
            "claude/x",
            date(2026, 10, 5),
            stale_branches=[
                ("claude/impl-branch", 55.0, 1, "isolated", "", "", "", 16, 5, ""),
                ("claude/doc-branch", 55.0, 1, "isolated", "", "", "", 0, 0, ""),
                ("claude/legacy-7tuple", 55.0, 1, "isolated", "", "", ""),
            ],
        )
        rows = text.splitlines()

        def row_after(branch: str) -> str:
            at = next(i for i, r in enumerate(rows) if r.startswith(f"  · {branch} "))
            return rows[at + 1] if at + 1 < len(rows) else ""

        assert "구현 신호: 신규 16파일" in row_after("claude/impl-branch")
        assert "구현 신호 없음" in row_after("claude/doc-branch")
        # 7튜플(구 호출부)은 신호 줄 없이 그대로 — 하위호환(미측정은 말하지 않는다)
        assert "구현 신호" not in row_after("claude/legacy-7tuple")


def _synthetic_scan(now: datetime):
    """구현 신호가 채워진 합성 스캔 결과 — 스캐너를 갈아끼워 CLI 배선만 본다."""
    return remote_claims.StaleBranchScanResult(
        "ok",
        stale=[
            remote_claims.StaleBranch(
                branch="claude/impl-isolated",
                ref="refs/remotes/origin/claude/impl-isolated",
                last_commit_at=now,
                age_days=55.0,
                ahead=1,
                status="isolated",
                impl_new=16,
                impl_changed=5,
            ),
            remote_claims.StaleBranch(
                branch="claude/doc-isolated",
                ref="refs/remotes/origin/claude/doc-isolated",
                last_commit_at=now,
                age_days=55.0,
                ahead=1,
                status="isolated",
                impl_new=0,
                impl_changed=0,
            ),
            remote_claims.StaleBranch(
                branch="claude/impl-closed",
                ref="refs/remotes/origin/claude/impl-closed",
                last_commit_at=now,
                age_days=41.0,
                ahead=2,
                status="pr_closed",
                evidence="PR #880 닫힘(미머지)",
                impl_new=6,
                impl_changed=15,
            ),
        ],
        pr_lookup_ok=True,
    )


class TestImplSignalCliWiring:
    """계산한 신호가 *사람이 보는 두 화면*(brief·branches)에 실제로 나가는가 — 정본화≠집행."""

    def test_brief_command_forwards_impl_signal_to_render(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = clone("brief-impl-signal")
        monkeypatch.chdir(mine)
        assert cli.main(["seed"]) == 0
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(
            remote_claims, "scan_stale_branches", lambda root, **kw: _synthetic_scan(now)
        )

        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        rows = capsys.readouterr().out.splitlines()

        def row_after(prefix: str) -> str:
            at = next(i for i, r in enumerate(rows) if r.startswith(prefix))
            return rows[at + 1]

        assert "신규 16파일 · 수정 5파일" in row_after("  · claude/impl-isolated ")
        assert "구현 신호 없음" in row_after("  · claude/doc-isolated ")
        assert "신규 6파일 · 수정 15파일" in row_after("  · claude/impl-closed ")

    def test_branches_command_prints_impl_signal(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = clone("branches-impl-signal")
        monkeypatch.chdir(mine)
        assert cli.main(["seed"]) == 0
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(
            remote_claims, "scan_stale_branches", lambda root, **kw: _synthetic_scan(now)
        )

        capsys.readouterr()
        assert cli.main(["branches"]) == 0
        rows = capsys.readouterr().out.splitlines()

        def row_after(prefix: str) -> str:
            at = next(i for i, r in enumerate(rows) if r.startswith(prefix))
            return rows[at + 1]

        assert "신규 16파일 · 수정 5파일" in row_after("  [고립] claude/impl-isolated ")
        assert "구현 신호 없음" in row_after("  [고립] claude/doc-isolated ")
        assert "신규 6파일 · 수정 15파일" in row_after("  [PR-닫힘] claude/impl-closed ")
