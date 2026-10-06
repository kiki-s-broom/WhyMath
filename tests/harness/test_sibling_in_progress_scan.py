"""형제 브랜치의 진행 중 사본 스캔 — done이 claim을 놓고 기록이 보이기까지의 착수 공백 (HARN-198).

**사고 형태** (2026-09-29 `S4-11-hint-content-generation` 이중 구현): 끝낸 세션의 `done`은 원격 claim을
즉시 걷는데, done을 담은 대장 변경은 그 세션의 작업 트리에만 있어 그 브랜치의 원격 사본은 push 전까지
`in_progress`다(실측 46분). 그 창에서 ⑴ 원격 claim 대장은 비었고 ⑵ 트렁크는 `todo`이며 ⑶ 미머지
done 스캔은 `status: done`만 본다 — 세 겹이 전부 비어 다음 세션이 같은 슬라이스를 다시 구현했다.
읽기측 탐지(`scan_remote_in_progress`)는 CAS가 실패할 때만 돌아 이 정상 환경에서는 불리지 않았다.

**픽스처는 진짜 git 원격이다** — 읽기 경로를 시임(fake)으로 검증하면 `cat-file --batch` 정렬·트렁크
해소·브랜치 ref 매핑이 전부 우회된다(HARN-193 `test_gate_attach_claim_gap.py`와 같은 이유).

**상태 대조** (사고 상태만 RED이고 나머지가 GREEN임을 가르지 못하면 검사가 아니라 고장이다):
    사고   — 형제 사본 in_progress · claim 대장 빔 · 트렁크 todo         → start 거부 · next·brief 제외
    대조군 — 팁이 ttl을 넘긴 방치 브랜치 · 트렁크에 이미 실린 태스크 · 트렁크에서 물려받은 사본 ·
             형제 사본이 todo · 내 세션의 사본 · 다른 브랜치가 없는 환경
"""

from __future__ import annotations

import inspect
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import remote_claims
import store
from models import Task

import backlog as cli

TASK = "T198-01-sibling-target"
OTHER_TASK = "T198-02-innocent-bystander"
TTL = 72


def _git(repo: Path, *argv: str) -> str:
    result = subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _write_task(
    repo: Path, status: str, session: str | None, task_id: str = TASK, **extra: object
) -> None:
    store.save_task(
        repo,
        Task(
            id=task_id,
            title=f"형제 스캔 대상 {task_id}",
            track="math-completion",
            stage="S1",
            eos_priority="P1",
            status=status,
            session=session,
            artifacts=["PR#0"] if status == "done" else [],
            **extra,
        ),
    )


class _World:
    """트렁크·형제 세션·나를 실제 git 으로 세운다."""

    def __init__(self, clone, monkeypatch):
        self.clone = clone
        self.monkeypatch = monkeypatch

    def chdir(self, repo: Path) -> None:
        self.monkeypatch.chdir(repo)

    def push_trunk(self, repo: Path, status: str, session: str | None, task_id: str = TASK) -> None:
        _git(repo, "checkout", "-q", "main")
        _write_task(repo, status, session, task_id)
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"trunk {status}")
        _git(repo, "push", "--quiet", "origin", "main")

    def push_branch(
        self, repo: Path, branch: str, status: str, session: str | None, task_id: str = TASK
    ) -> None:
        _git(repo, "checkout", "-q", "-B", branch)
        _write_task(repo, status, session, task_id)
        _git(repo, "add", ".")
        # 트렁크와 같은 상태의 사본(물려받은 경우)은 변경이 없어 빈 커밋을 허용해야 한다
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"{status} {task_id}")
        _git(repo, "push", "--quiet", "-u", "origin", branch)

    def landed_trunk(self, *task_ids: str) -> None:
        """트렁크에 todo 태스크들이 착지한 상태 — CLI 가 읽는 seed 대장 위에."""
        lander = self.clone("lander")
        self.chdir(lander)
        assert cli.main(["seed"]) == 0
        for task_id in task_ids:
            _write_task(lander, "todo", None, task_id)
        _git(lander, "add", ".")
        _git(lander, "commit", "-q", "-m", "trunk state (test)")
        _git(lander, "push", "--quiet", "origin", "HEAD:main")

    def finisher_in_the_gap(self, name: str = "finisher", task_id: str = TASK) -> Path:
        """사고의 창을 만든다 — start(claim) → 브랜치 push(사본 in_progress) → 원격 claim 해제.

        `done`이 하는 일 중 이 공백을 여는 것은 마지막(원격 claim 해제)이고, done 기록은 push 전이라
        원격 사본은 in_progress 그대로다. 해제는 `done`이 쓰는 경로(`_release_remote_claim`)와 같은
        `remote_claims.release`를 부른다.
        """
        finisher = self.clone(name)
        self.chdir(finisher)
        assert cli.main(["start", task_id]) == 0
        _git(finisher, "add", ".")
        _git(finisher, "commit", "-q", "-m", f"start {task_id}")
        _git(finisher, "push", "--quiet", "-u", "origin", f"claude/{name}")
        released = remote_claims.release(finisher, task_id, f"claude/{name}")
        assert released.status == "ok", released
        return finisher

    def newcomer(self, name: str = "newcomer") -> Path:
        mine = self.clone(name)
        self.chdir(mine)
        return mine


def _world(bare_remote, monkeypatch) -> _World:
    _, clone = bare_remote
    return _World(clone, monkeypatch)


def _scan(repo: Path, *task_ids: str, session: str = "claude/newcomer", **kw):
    kw.setdefault("ttl_hours", TTL)
    kw.setdefault("refs_fresh", True)
    return remote_claims.scan_sibling_in_progress(repo, task_ids or [TASK], session=session, **kw)


# ═════════════════════════════════════════════════════════════════════════
# 사고 상태 — 형제 사본은 in_progress 이고 claim 대장은 비었고 트렁크는 todo
# ═════════════════════════════════════════════════════════════════════════
class TestAccidentState:
    def test_premise_the_three_existing_layers_are_all_blind(self, bare_remote, monkeypatch):
        """전제 고정 — 사고 창에서 기존 세 겹(claim·트렁크·미머지 done)은 전부 비어 있다.

        이 단언이 깨지면 아래 거부 테스트들은 기존 검사의 거부와 구분되지 않아 새 스캔이 아니라
        기존 검사를 검증하는 공허한 테스트가 된다.
        """
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        mine = w.newcomer()
        backlog, _ = store.load_backlog(mine)
        assert backlog.tasks[TASK].status == "todo"  # ⑵ 트렁크 사본 = todo
        claims, status = remote_claims.list_claims(mine)
        assert status == "ok" and [c.task_id for c in claims] == []  # ⑴ claim 대장 빔
        done_map, done_status = remote_claims.scan_remote_done(mine, [TASK], fetch=True)
        assert (done_map, done_status) == ({}, "ok")  # ⑶ 미머지 done 스캔도 못 본다

    def test_start_refuses_and_names_branch_and_status(self, bare_remote, monkeypatch, capsys):
        """start가_형제의_진행_중_사본을_거부하고_브랜치와_상태를_말한다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        w.newcomer()
        capsys.readouterr()
        assert cli.main(["start", TASK]) == 1
        err = capsys.readouterr().err
        assert "HARN-198" in err
        assert "claude/finisher" in err and "in_progress" in err
        assert "git show origin/claude/finisher:backlog/tasks/" in err, "확인 명령을 안내해야 한다"
        assert "--ignore-remote-claim" in err, "우회 경로를 안내해야 한다"

    def test_refused_start_leaves_no_claim_behind(self, bare_remote, monkeypatch):
        """거부된_start는_원격_claim을_남기지_않는다(dangling_claim_방지)"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        mine = w.newcomer()
        assert cli.main(["start", TASK]) == 1
        claims, status = remote_claims.list_claims(mine)
        assert status == "ok" and [c.task_id for c in claims] == []
        backlog, _ = store.load_backlog(mine)
        assert backlog.tasks[TASK].status == "todo"

    def test_next_excludes_the_task_and_says_why(self, bare_remote, monkeypatch, capsys):
        """next가_후보에서_제외하고_이유를_말한다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        w.newcomer()
        capsys.readouterr()
        assert cli.main(["next", "--n", "20"]) == 0
        captured = capsys.readouterr()
        assert TASK not in captured.out, "진행 중으로 들린 태스크가 후보로 노출되면 안 된다"
        assert "후보 제외" in captured.err and TASK in captured.err
        assert "claude/finisher" in captured.err

    def test_brief_excludes_the_task_and_says_why_on_stdout(self, bare_remote, monkeypatch, capsys):
        """brief가_후보에서_제외하고_이유를_stdout에_싣는다 — 훅이 stderr를 버리므로"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        w.newcomer()
        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out
        candidates = out.split("다음 착수 후보")[-1] if "다음 착수 후보" in out else ""
        assert TASK not in candidates, "브리핑 후보로 노출되면 안 된다"
        assert f"후보 제외 {TASK}" in out and "claude/finisher" in out

    def test_ignore_remote_claim_bypasses_and_leaves_an_event(
        self, bare_remote, monkeypatch, capsys
    ):
        """--ignore-remote-claim으로_우회할_수_있고_사유가_이벤트로_남는다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        mine = w.newcomer()
        capsys.readouterr()
        assert cli.main(["start", TASK, "--ignore-remote-claim"]) == 0
        assert "중복 구현 위험" in capsys.readouterr().err
        events = "".join(
            p.read_text(encoding="utf-8") for p in (mine / "backlog").rglob("*.ndjson")
        )
        assert "start_ignored_sibling_in_progress" in events
        assert "claude/finisher:in_progress" in events

    def test_review_status_copy_is_also_a_holder(self, bare_remote, monkeypatch):
        """review_상태의_형제_사본도_홀더다 — 검토 대기 중인 작업을 다시 구현하면 이중이다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        sibling = w.clone("reviewer")
        w.push_branch(sibling, "claude/reviewer", "review", "claude/reviewer")
        mine = w.newcomer()
        scan = _scan(mine)
        assert [(h.branch, h.status) for h in scan.found[TASK]] == [("claude/reviewer", "review")]

    def test_only_the_task_the_sibling_holds_is_flagged(self, bare_remote, monkeypatch):
        """태스크별_독립 — 형제가_든_태스크만_잡고_옆_태스크는_건드리지_않는다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK, OTHER_TASK)
        w.finisher_in_the_gap(task_id=TASK)
        mine = w.newcomer()
        scan = _scan(mine, TASK, OTHER_TASK)
        assert scan.status == "ok"
        assert set(scan.found) == {TASK}, "옆 태스크가 같이 잡히면 과잉 차단이다"

    def test_two_siblings_are_all_reported(self, bare_remote, monkeypatch, capsys):
        """둘_이상의_형제가_같은_태스크를_들고_있으면_전부_보고한다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        a, b = w.clone("sib-a"), w.clone("sib-b")
        w.push_branch(a, "claude/sib-a", "in_progress", "claude/sib-a")
        w.push_branch(b, "claude/sib-b", "in_progress", "claude/sib-b")
        w.newcomer()
        capsys.readouterr()
        assert cli.main(["start", TASK]) == 1
        err = capsys.readouterr().err
        for needle in ("claude/sib-a", "claude/sib-b"):
            assert needle in err, f"{needle} 누락 — 경쟁 세션이 가려지면 택일 판단이 틀어진다"


# ═════════════════════════════════════════════════════════════════════════
# 대조군 — 과탐 방어. 모든 착수를 막는 검사는 검사가 아니다.
# ═════════════════════════════════════════════════════════════════════════
class TestFalsePositiveGuards:
    def test_abandoned_branch_past_ttl_does_not_block(self, bare_remote, monkeypatch):
        """팁이_ttl을_넘긴_방치_브랜치는_막지_않는다(과탐_완화) — 사유와_함께_skipped로_남는다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        mine = w.newcomer()
        future = datetime.now(timezone.utc) + timedelta(hours=TTL + 1)
        scan = _scan(mine, now=future)
        assert scan.found == {}
        assert [(s.branch, s.reason) for s in scan.skipped] == [("claude/finisher", "tip_stale")]

    def test_unknown_tip_age_counts_as_holder_not_stale(self, bare_remote, monkeypatch):
        """팁_시각을_못_읽으면_홀더로_센다 — 모른다를_오래됐다로_접으면_살아_있는_세션을_놓친다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        mine = w.newcomer()
        monkeypatch.setattr(remote_claims, "_ref_tip_times", lambda _root: {})
        scan = _scan(mine)
        assert [(h.branch, h.tip_age_hours) for h in scan.found[TASK]] == [
            ("claude/finisher", None)
        ]
        assert scan.skipped == []

    def test_same_branch_within_ttl_still_blocks(self, bare_remote, monkeypatch):
        """위_대조군의_역 — ttl_안의_같은_브랜치는_막는다(방어가_보호를_무력화하지_않는다)"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.finisher_in_the_gap()
        mine = w.newcomer()
        near = datetime.now(timezone.utc) + timedelta(hours=TTL - 1)
        scan = _scan(mine, now=near)
        assert [h.branch for h in scan.found[TASK]] == ["claude/finisher"]
        assert scan.skipped == []

    def test_task_already_settled_on_trunk_is_residue_not_holder(self, bare_remote, monkeypatch):
        """트렁크가_이미_done이면 사본의_in_progress는_잔재다(규칙_A와_동형)"""
        w = _world(bare_remote, monkeypatch)
        a = w.clone("session-a")
        w.push_trunk(a, "done", None)
        w.push_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        mine = w.newcomer()
        scan = _scan(mine)
        assert scan.found == {}
        assert [(s.branch, s.reason) for s in scan.skipped] == [
            ("claude/session-a", "trunk_settled")
        ]

    def test_state_inherited_from_trunk_is_not_a_claim_by_that_branch(
        self, bare_remote, monkeypatch
    ):
        """트렁크에서_물려받은_사본은_그_브랜치의_claim이_아니다"""
        w = _world(bare_remote, monkeypatch)
        a = w.clone("session-a")
        w.push_trunk(a, "in_progress", "claude/original")
        # 트렁크 상태 그대로 물려받아 만든 브랜치 — 같은 상태·같은 session
        inheritor = w.clone("inheritor")
        w.push_branch(inheritor, "claude/inheritor", "in_progress", "claude/original")
        mine = w.newcomer()
        scan = _scan(mine)
        assert scan.found == {}
        assert [(s.branch, s.reason) for s in scan.skipped] == [
            ("claude/inheritor", "trunk_inherited")
        ]

    def test_a_different_holder_than_trunk_still_counts(self, bare_remote, monkeypatch):
        """위_대조군의_역 — 트렁크와_다른_session이_잡았다면_그건_진짜_claim이다"""
        w = _world(bare_remote, monkeypatch)
        a = w.clone("session-a")
        w.push_trunk(a, "in_progress", "claude/original")
        taker = w.clone("taker")
        w.push_branch(taker, "claude/taker", "in_progress", "claude/taker")
        mine = w.newcomer()
        scan = _scan(mine)
        assert [h.branch for h in scan.found[TASK]] == ["claude/taker"]

    def test_sibling_copy_that_is_todo_is_not_a_holder(self, bare_remote, monkeypatch):
        """형제_사본이_todo면_막지_않는다(unblock으로_놓은_세션) — 그리고_start가_성공한다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        sibling = w.clone("released")
        w.push_branch(sibling, "claude/released", "todo", None)
        mine = w.newcomer()
        assert _scan(mine).found == {}
        assert cli.main(["start", TASK]) == 0

    def test_blocked_sibling_copy_is_not_a_holder(self, bare_remote, monkeypatch):
        """blocked는_홀더가_아니다 — 차단_홀드는_원격_claim이_따로_보호한다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        sibling = w.clone("blocker")
        w.push_branch(sibling, "claude/blocker", "blocked", None)
        mine = w.newcomer()
        assert _scan(mine).found == {}

    def test_my_own_session_copy_does_not_block_me(self, bare_remote, monkeypatch):
        """내_세션의_사본은_나를_막지_않는다 — 이전_컨테이너에서_push한_내_claim"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        earlier = w.clone("earlier")
        w.push_branch(earlier, "claude/earlier", "in_progress", "claude/me")
        mine = w.newcomer()
        scan = _scan(mine, session="claude/me")
        assert scan.found == {}
        assert [(s.branch, s.reason) for s in scan.skipped] == [("claude/earlier", "own_session")]

    def test_excluded_branch_is_not_scanned(self, bare_remote, monkeypatch):
        """exclude_branches로_넘긴_내_브랜치는_보지_않는다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        sibling = w.clone("self-pushed")
        w.push_branch(sibling, "claude/self-pushed", "in_progress", "claude/other")
        mine = w.newcomer()
        assert _scan(mine, exclude_branches=["claude/self-pushed"]).found == {}

    def test_no_other_branches_allows_start_and_lists_the_task(
        self, bare_remote, monkeypatch, capsys
    ):
        """다른_브랜치가_없으면_착수되고_후보에_보인다 — 브랜치_존재만으로_막으면_고장이다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.newcomer()
        capsys.readouterr()
        assert cli.main(["next", "--n", "20"]) == 0
        assert TASK in capsys.readouterr().out
        assert cli.main(["start", TASK]) == 0


# ═════════════════════════════════════════════════════════════════════════
# 측정 실패는 통과가 아니다 — 스캔 자신의 실패를 '형제 없음'으로 접지 않는다
# ═════════════════════════════════════════════════════════════════════════
class TestScanFailureIsNotPass:
    def test_unfetched_clone_with_no_branches_reports_no_refs(self, bare_remote, monkeypatch):
        """캐시에_다른_브랜치가_0개이고_최신화_선언도_없으면_no_refs다(안_봤다)"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        mine = w.newcomer()
        scan = _scan(mine, refs_fresh=False)
        assert scan.status == "no_refs" and scan.found == {}

    def test_declared_fresh_with_no_branches_is_ok(self, bare_remote, monkeypatch):
        """최신화를_선언했고_정말_브랜치가_없으면_ok다 — 위_no_refs와_가르는_대조군"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        mine = w.newcomer()
        scan = _scan(mine, refs_fresh=True)
        assert scan.status == "ok" and scan.found == {}

    def test_no_remote_is_offline_not_empty_ok(self, git_repo):
        """원격이_없으면_offline이다 — 빈_결과를_ok로_돌려주지_않는다"""
        scan = remote_claims.scan_sibling_in_progress(
            git_repo, [TASK], session="claude/x", ttl_hours=TTL
        )
        assert scan.status == "offline" and scan.found == {}

    def test_fetch_failure_is_reported_not_swallowed(self, bare_remote, monkeypatch):
        """fetch가_실패하면_ok가_아니다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        mine = w.newcomer()
        _git(mine, "remote", "set-url", "origin", str(mine / "does-not-exist.git"))
        scan = _scan(mine, fetch=True, refs_fresh=False)
        assert scan.status != "ok" and scan.found == {}

    def test_ref_limit_marks_truncated_and_keeps_findings(self, bare_remote, monkeypatch):
        """브랜치_수가_상한을_넘으면_truncated — 발견분은_유효하다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        a, b = w.clone("sib-a"), w.clone("sib-b")
        w.push_branch(a, "claude/sib-a", "in_progress", "claude/sib-a")
        w.push_branch(b, "claude/sib-b", "in_progress", "claude/sib-b")
        mine = w.newcomer()
        scan = _scan(mine, max_refs=1)
        # 형제 브랜치 2개에 상한 1 — 하나만 봤으니 truncated이고, 본 것은 발견분으로 남는다
        assert scan.status == "truncated"
        assert len(scan.found[TASK]) == 1 and scan.scanned_refs == 1

    def test_misaligned_batch_is_an_error_not_a_silent_zip(self, bare_remote, monkeypatch):
        """cat-file_배치_응답과_요청의_수가_어긋나면_error다 — 엉뚱한_브랜치에_붙이지_않는다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        a = w.clone("sib-a")
        w.push_branch(a, "claude/sib-a", "in_progress", "claude/sib-a")
        mine = w.newcomer()
        monkeypatch.setattr(remote_claims, "_iter_batch_blobs", lambda _stdout: iter([None]))
        scan = _scan(mine)
        assert scan.status == "error:BatchMisaligned" and scan.found == {}

    def test_start_warns_when_scan_status_is_not_ok(self, bare_remote, monkeypatch, capsys):
        """start는_스캔_판정_불가를_'형제_없음'으로_위장하지_않고_경고한다"""
        w = _world(bare_remote, monkeypatch)
        w.landed_trunk(TASK)
        w.newcomer()
        real = remote_claims.scan_sibling_in_progress

        def broken(*args, **kwargs):
            return remote_claims.SiblingScan("error:Boom")

        monkeypatch.setattr(remote_claims, "scan_sibling_in_progress", broken)
        capsys.readouterr()
        assert cli.main(["start", TASK]) == 0  # 판정 불가는 fail-open이되 침묵하지 않는다
        assert "형제 브랜치 진행 중 탐지 불가(error:Boom)" in capsys.readouterr().err
        assert real is not broken


# ═════════════════════════════════════════════════════════════════════════
# 집행 지점 — 함수가 존재한다는 것과 서빙 경로가 그것을 부른다는 것은 다르다
# ═════════════════════════════════════════════════════════════════════════
class TestEnforcementWiring:
    @pytest.mark.parametrize("fn_name", ["cmd_start", "cmd_next", "cmd_brief"])
    def test_serving_paths_call_the_scan(self, fn_name):
        """cmd_start·cmd_next·cmd_brief가_스캔을_실제로_부른다(소스_배선_동결)"""
        source = inspect.getsource(getattr(cli, fn_name))
        assert "scan_sibling_in_progress(" in source, f"{fn_name}이 스캔을 부르지 않는다"

    def test_start_scan_is_independent_of_cas_outcome(self):
        """start의_스캔은_CAS_실패_분기_안이_아니라_앞단에서_돈다 — 이_사고는_CAS가_성공한_환경이다"""
        source = inspect.getsource(cli.cmd_start)
        scan_at = source.index("scan_sibling_in_progress(")
        cas_at = source.index("remote_claims.claim(root, task.id, session)")
        assert scan_at < cas_at, "스캔이 원격 claim(CAS) 뒤로 밀리면 CAS 결과에 종속된다"
        fallback_at = source.index("scan_remote_in_progress(root, task.id, session)")
        assert scan_at < fallback_at
