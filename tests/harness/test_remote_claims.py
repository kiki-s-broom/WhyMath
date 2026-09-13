"""remote_claims.py — 원격 claim(harness-claims 브랜치) CAS 원자성·폴백·청소 테스트.

가짜 git이 아니라 진짜 로컬 bare 원격으로 병렬 세션 레이스를 재현한다 — 시임이면
`--force-with-lease`의 서버측 트랜잭션을 검증할 수 없고, 그게 이 모듈의 존재 이유다.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import remote_claims
from models import Backlog, Task

TASK = "S1-01-sample-task"


def _mk_backlog(status: str = "in_progress", session: str | None = "claude/a") -> Backlog:
    backlog = Backlog(stage_order=["S1"])
    backlog.tasks[TASK] = Task(
        id=TASK,
        title="샘플",
        track="math-completion",
        stage="S1",
        status=status,
        session=session,
    )
    return backlog


class TestClaimCAS:
    def test_claim_success_creates_remote_ref(self, bare_remote):
        """claim_성공_후_ls_remote에_ref_존재"""
        _, clone = bare_remote
        a = clone("session-a")
        result = remote_claims.claim(a, TASK, "claude/session-a")
        assert result.status == "ok"
        claims, status = remote_claims.list_claims(a, with_meta=True)
        assert status == "ok"
        assert [c.task_id for c in claims] == [TASK]
        assert claims[0].branch == "claude/session-a"
        assert claims[0].ts  # UTC ISO8601 타임스탬프 기록됨

    def test_race_only_one_of_two_sessions_succeeds(self, bare_remote):
        """레이스_두_세션_중_한쪽만_성공"""
        # 핵심 시나리오: A claim 후 B가 같은 태스크 claim → B는 conflict
        _, clone = bare_remote
        a = clone("session-a")
        b = clone("session-b")
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        result_b = remote_claims.claim(b, TASK, "claude/session-b")
        assert result_b.status == "conflict"
        # conflict 시 상대 claim 정보가 조회된다
        assert result_b.claim is not None
        assert result_b.claim.branch == "claude/session-a"

    def test_reclaim_possible_after_release(self, bare_remote):
        """release_후_재claim_가능"""
        _, clone = bare_remote
        a = clone("session-a")
        b = clone("session-b")
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        assert remote_claims.release(a, TASK, "claude/session-a").status == "ok"
        assert remote_claims.claim(b, TASK, "claude/session-b").status == "ok"

    def test_different_tasks_claim_independently(self, bare_remote):
        """서로_다른_태스크는_독립_claim"""
        _, clone = bare_remote
        a = clone("session-a")
        b = clone("session-b")
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        assert remote_claims.claim(b, "S1-02-other-task", "claude/session-b").status == "ok"

    # ── HARN-09 — 단일 브랜치 레이아웃이 새로 만든 계약 ────────────────────────

    def test_contention_different_tasks_both_survive(self, bare_remote):
        """경합해도_서로_다른_태스크는_둘_다_살아남는다

        lease 경합 재시도가 **기능을 죽이지 않는다**.

        단일 브랜치라 서로 다른 태스크를 claim해도 같은 ref를 갱신한다. 재시도가 없으면
        경합한 쪽이 실패하고 "한 번에 한 세션만 claim 가능"이라는 치명적 퇴행이 된다.

        ⚠️ **진짜 경합을 만들어야 한다**: 순차 호출은 매번 최신 base를 fetch하므로
        lease가 절대 깨지지 않는다(초안이 그랬고, `CAS_RETRIES=1` 돌연변이를 못 잡아
        무효 검사임이 드러났다). 그래서 B가 base를 읽은 *뒤* push하기 *직전*에 A를
        끼워넣어 B의 lease를 강제로 낡게 만든다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        b = clone("session-b")

        original_push = remote_claims._push_claims
        attempts: list[str] = []

        def racing_push(root, base_sha, commit_sha):
            attempts.append(base_sha)
            if len(attempts) == 1:
                # B가 base를 읽은 뒤 push하기 직전에 A가 먼저 착륙 → B의 lease는 낡는다
                remote_claims._push_claims = original_push
                assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
                remote_claims._push_claims = racing_push
            return original_push(root, base_sha, commit_sha)

        remote_claims._push_claims = racing_push
        try:
            result = remote_claims.claim(b, "S1-02-other-task", "claude/session-b")
        finally:
            remote_claims._push_claims = original_push

        assert result.status == "ok", f"lease 경합에서 재시도가 실패했다: {result.message}"
        assert len(attempts) >= 2, "경합이 재현되지 않았다 — 이 테스트는 재시도를 검증하지 못한다"
        claims, status = remote_claims.list_claims(a)
        assert status == "ok"
        assert {c.task_id for c in claims} == {TASK, "S1-02-other-task"}, "경합이 claim을 삼켰다"

    def test_claim_does_not_touch_worktree_or_index(self, bare_remote):
        """claim은_작업트리와_인덱스를_건드리지_않는다

        트리를 `mktree`로 만드는 이유 — 인덱스를 쓰면 사용자 스테이징이 오염된다.

        하네스는 개발자가 편집 중인 클론에서 그대로 돈다. claim 하나가 스테이징을
        흔들면 그건 도구가 아니라 사고다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        # 스테이징된 것 *과* 스테이징되지 않은 것을 **둘 다** 만든다.
        # 스테이징만 있으면 `git add -A` 류의 오염이 무변화로 보여 검사가 무효가 된다
        # (초안이 그랬고 돌연변이를 못 잡았다). 미스테이징 파일이 있어야 변별력이 산다.
        (a / "스테이징됨.txt").write_text("staged", encoding="utf-8")
        subprocess.run(["git", "add", "스테이징됨.txt"], cwd=a, check=True, capture_output=True)
        (a / "미스테이징.txt").write_text("untracked", encoding="utf-8")
        before = subprocess.run(
            ["git", "status", "--porcelain"], cwd=a, capture_output=True, text=True
        ).stdout
        assert "??" in before, "미스테이징 상태가 만들어지지 않으면 이 검사는 변별력이 없다"

        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        assert remote_claims.release(a, TASK, "claude/session-a").status == "ok"

        after = subprocess.run(
            ["git", "status", "--porcelain"], cwd=a, capture_output=True, text=True
        ).stdout
        assert after == before, f"claim/release가 작업트리를 오염시켰다:\n{before!r} → {after!r}"

    def test_release_does_not_use_ref_deletion(self, bare_remote):
        """해제는_ref_삭제를_쓰지_않는다

        이 환경의 프록시가 ref 삭제를 거부하므로 삭제 push는 설계상 금지다.

        구현이 삭제 push로 회귀하면 실 환경에서만 조용히 깨진다(로컬 bare 원격은
        삭제를 허용하므로 이 테스트 없이는 안 잡힌다) — 그래서 명령을 직접 감시한다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"

        original = remote_claims._git
        seen: list[tuple[str, ...]] = []

        def spy_git(root, *argv, **kwargs):
            seen.append(argv)
            return original(root, *argv, **kwargs)

        remote_claims._git = spy_git
        try:
            assert remote_claims.release(a, TASK, "claude/session-a").status == "ok"
        finally:
            remote_claims._git = original

        deletions = [
            argv
            for argv in seen
            if argv and argv[0] == "push" and any(a_.startswith(":") for a_ in argv)
        ]
        assert not deletions, f"삭제 push가 쓰였다 — 실 프록시에서 거부된다: {deletions}"
        claims, status = remote_claims.list_claims(a)
        assert status == "ok" and claims == []

    def test_missing_claim_branch_not_mistaken_for_query_failure(self, bare_remote):
        """claim_브랜치_부재가_조회_실패로_오인되지_않는다

        claim 0건은 정상 상태다 — ok로 보고돼야 후속 로직이 진행된다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        claims, status = remote_claims.list_claims(a)
        assert claims == [] and status == "ok"

    def test_corrupted_meta_claim_not_silently_hijacked(self, bare_remote, monkeypatch):
        """메타가_파손된_claim은_조용히_탈취되지_않는다

        홀더를 특정 못 해도 **통과가 아니라 conflict**다.

        "누가 잡았는지 모르니 일단 진행"은 조용한 탈취이고, 그게 이 모듈이 막으려는
        바로 그 사고(OPS-07·OPS-12 병렬 중복 구현)다. 복구는 --force로 명시한다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        b = clone("session-b")
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"

        # 메타 파손 재현 — 브랜치 필드를 읽을 수 없는 상태
        original_read = remote_claims._read_claims

        def corrupt_read(root, base_sha):
            claims = original_read(root, base_sha)
            for c in claims:
                c.branch = ""
                c.meta = None
            return claims

        monkeypatch.setattr(remote_claims, "_read_claims", corrupt_read)
        result = remote_claims.claim(b, TASK, "claude/session-b")
        assert result.status == "conflict", "홀더 불명이 통과로 이어지면 조용한 탈취다"
        assert "--force" in result.message, "복구 경로를 안내해야 막힌 채로 남지 않는다"


class TestReleaseSafety:
    def test_releasing_others_claim_requires_force(self, bare_remote):
        """남의_claim_해제는_force_필수"""
        _, clone = bare_remote
        a = clone("session-a")
        b = clone("session-b")
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        denied = remote_claims.release(b, TASK, "claude/session-b")
        assert denied.status == "error"
        assert "force" in denied.message
        forced = remote_claims.release(b, TASK, "claude/session-b", force=True)
        assert forced.status == "ok"

    def test_release_of_nonexistent_claim_is_idempotent(self, bare_remote):
        """없는_claim_해제는_멱등"""
        _, clone = bare_remote
        a = clone("session-a")
        assert remote_claims.release(a, TASK, "claude/session-a").status == "ok"


class TestFailOpen:
    def test_repo_without_remote_is_offline(self, git_repo: Path):
        """원격_없는_저장소는_offline"""
        result = remote_claims.claim(git_repo, TASK, "claude/x")
        assert result.status == "offline"

    def test_dead_remote_returns_offline_or_error_never_raises(self, git_repo: Path, tmp_path):
        """죽은_원격은_offline_또는_error_절대_예외_아님"""
        import subprocess

        subprocess.run(
            ["git", "remote", "add", "origin", str(tmp_path / "no-such-repo.git")],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        result = remote_claims.claim(git_repo, TASK, "claude/x")
        assert result.status in ("offline", "error")

    def test_list_claims_without_remote_is_offline(self, git_repo: Path):
        """list_claims_원격_없으면_offline"""
        claims, status = remote_claims.list_claims(git_repo)
        assert claims == []
        assert status == "offline"


class TestTopLevelFieldParser:
    """태스크 YAML 최상위 스칼라 파서 — PyYAML 비의존 (하네스 의존성 0 설계)."""

    def test_parses_real_dump_task_format(self):
        """실제_dump_task_형식을_읽는다"""
        import store

        body = store.dump_task(
            Task(
                id=TASK,
                title="샘플: 콜론 포함",
                track="math-completion",
                stage="S1",
                status="in_progress",
                session="claude/session-a",
                paths=["scripts/harness/**"],
            )
        )
        assert remote_claims._top_level_field(body, "status") == "in_progress"
        assert remote_claims._top_level_field(body, "session") == "claude/session-a"

    def test_null_session_yields_empty_string(self):
        """null_세션은_빈_문자열"""
        body = "id: X\nstatus: todo\nsession: null\n"
        assert remote_claims._top_level_field(body, "session") == ""

    def test_strips_quotes_from_quoted_value(self):
        """인용된_값의_따옴표를_벗긴다"""
        body = 'status: "in_progress"\nsession: "claude/a-b"\n'
        assert remote_claims._top_level_field(body, "session") == "claude/a-b"

    def test_ignores_indented_lines_and_colons_inside_values(self):
        """들여쓰기된_줄과_값_속_콜론에_속지_않는다"""
        # notes 값 안의 'status: in_progress'와 리스트 항목이 최상위로 오인되면 안 된다
        body = (
            "status: todo\n"
            'notes: "이전 세션에서 status: in_progress 였음"\n'
            'acceptance:\n  - "status: in_progress 금지"\n'
        )
        assert remote_claims._top_level_field(body, "status") == "todo"

    def test_missing_key_yields_empty_string(self):
        """없는_키는_빈_문자열"""
        assert remote_claims._top_level_field("id: X\n", "session") == ""


class TestReadSideScan:
    """읽기측 교차 세션 탐지 (HARN-07) — CAS가 막힌 환경의 폴백.

    쓰기(refs/claims push)가 403인 환경을 가정하되, 읽기 경로는 진짜 로컬 원격에서
    실제 git fetch/show로 검증한다(시임 아님).
    """

    def _push_task_copy(
        self, repo: Path, branch: str, status: str, session: str | None, task_id: str = TASK
    ) -> None:
        """원격 브랜치에 태스크 YAML 사본을 심는다 — 타 세션이 push한 상태 재현."""
        import subprocess

        import store

        def run(*argv: str) -> None:
            subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)

        store.save_task(
            repo,
            Task(
                id=task_id,
                title="샘플",
                track="math-completion",
                stage="S1",
                status=status,
                session=session,
            ),
        )
        run("checkout", "-B", branch)
        run("add", ".")
        run("commit", "-m", f"claim {task_id}")
        run("push", "--quiet", "-u", "origin", branch)

    def test_detects_other_session_in_progress(self, bare_remote):
        """타_세션_in_progress를_탐지한다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_task_copy(a, "claude/session-a", "in_progress", "claude/session-a")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status == "ok"
        assert [(h.branch, h.session) for h in result.holders] == [
            ("claude/session-a", "claude/session-a")
        ]

    def test_own_session_in_progress_does_not_block_self(self, bare_remote):
        """내_세션의_in_progress는_나를_막지_않는다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        # 원격에 남은 claim의 session이 '나'인 경우 (내 브랜치를 이미 push한 상태)
        self._push_task_copy(a, "claude/session-b", "in_progress", "claude/session-b")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status == "ok"
        assert result.holders == []

    def test_todo_status_is_not_detected(self, bare_remote):
        """todo_상태는_탐지하지_않는다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_task_copy(a, "claude/session-a", "todo", None)
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status == "ok"
        assert result.holders == []

    def test_branch_without_task_file_skipped(self, bare_remote):
        """태스크_파일이_없는_브랜치는_건너뛴다"""
        _, clone = bare_remote
        _, b = clone("session-a"), clone("session-b")
        # main에는 backlog/ 자체가 없다 — 예외 없이 조용히 넘어가야 한다
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status == "ok"
        assert result.holders == []
        assert result.scanned_refs >= 1

    def test_ignores_claims_for_different_task(self, bare_remote):
        """다른_태스크의_claim에는_반응하지_않는다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_task_copy(
            a, "claude/session-a", "in_progress", "claude/session-a", task_id="S1-99-other-task"
        )
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status == "ok"
        assert result.holders == []

    def test_scan_without_remote_is_offline(self, git_repo: Path):
        """원격_없으면_offline_판정불가"""
        result = remote_claims.scan_remote_in_progress(git_repo, TASK, "claude/x")
        assert result.status == "offline"
        assert result.holders == []  # 빈 holders를 '충돌 없음'으로 읽으면 안 된다

    def test_fetch_failure_reported_as_status_not_exception(self, bare_remote, monkeypatch):
        """fetch_실패는_상태로_보고되고_예외가_아니다"""
        _, clone = bare_remote
        b = clone("session-b")
        original = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv and argv[0] == "fetch" and any("refs/heads" in a for a in argv):
                return subprocess.CompletedProcess(
                    ["git", *argv],
                    128,
                    stdout="",
                    stderr="fatal: unable to access 'origin': The requested URL returned error: 403",
                )
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status in ("offline", "error")
        assert result.holders == []
        assert "403" in result.message  # 침묵 실패 금지 — 원인이 메시지에 남는다

    def test_exceeding_branch_cap_reports_truncated(self, bare_remote):
        """브랜치_상한_초과는_truncated로_보고된다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_task_copy(a, "claude/session-a", "in_progress", "claude/session-a")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b", max_refs=1)
        assert result.status == "ok"
        assert result.scanned_refs == 1
        assert result.truncated is True  # 조용한 축소 금지


class TestReadSideStaleHandling:
    """HARN-08 — 머지·폐기 브랜치에 남은 in_progress 과탐 해소 (규칙 A·B).

    SQUASH 머지 저장소라 조상 검사(`merge-base --is-ancestor`)는 쓸 수 없다 —
    머지된 브랜치도 트렁크의 조상이 아니다(2026-07-27 5건 전수 실측). 대신
    트렁크 사본의 status(규칙 A)와 "트렁크는 세션이 아니다"(규칙 B)로 판별한다.
    """

    def _write_task(
        self, repo: Path, status: str, session: str | None, task_id: str = TASK
    ) -> None:
        import store

        store.save_task(
            repo,
            Task(
                id=task_id,
                title="샘플",
                track="math-completion",
                stage="S1",
                status=status,
                session=session,
                artifacts=["PR#0"] if status == "done" else [],
            ),
        )

    def _run(self, repo: Path, *argv: str) -> None:
        subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)

    def _push_trunk(
        self, repo: Path, status: str, session: str | None = None, task_id: str = TASK
    ) -> None:
        """트렁크(origin/main)에 태스크 사본을 심는다 — 규칙 A·B의 신호원."""
        self._run(repo, "checkout", "-q", "main")
        self._write_task(repo, status, session, task_id)
        self._run(repo, "add", ".")
        self._run(repo, "commit", "-q", "-m", f"trunk {status}")
        self._run(repo, "push", "--quiet", "origin", "main")

    def _push_session_branch(
        self, repo: Path, branch: str, status: str, session: str | None, task_id: str = TASK
    ) -> None:
        """세션 브랜치에 태스크 사본을 심는다 (홀더 후보)."""
        self._run(repo, "checkout", "-q", "-B", branch)
        self._write_task(repo, status, session, task_id)
        self._run(repo, "add", ".")
        self._run(repo, "commit", "-q", "-m", f"claim {task_id}")
        self._run(repo, "push", "--quiet", "-u", "origin", branch)

    def test_rule_a_trunk_done_excludes_holder_as_stale(self, bare_remote):
        """규칙A_트렁크가_done이면_홀더는_stale로_제외된다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_trunk(a, "done")
        self._push_session_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status == "ok"
        assert result.holders == []  # 과탐 해소 — 착수 허용
        assert result.trunk_status == "done"
        # 조용히 버리지 않는다 — 무엇을 왜 무시했는지 남는다
        assert [(s.branch, s.reason) for s in result.skipped] == [
            ("claude/session-a", "trunk_done")
        ]

    def test_rule_a_inverse_trunk_todo_still_blocks(self, bare_remote):
        """규칙A_역_트렁크가_todo면_여전히_차단한다"""
        # 규칙 A가 보호를 과잉 무력화하면 안 된다 — 착륙하지 않은 태스크는 그대로 막힌다
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_trunk(a, "todo")
        self._push_session_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status == "ok"
        assert [(h.branch, h.session) for h in result.holders] == [
            ("claude/session-a", "claude/session-a")
        ]
        assert result.skipped == []

    def test_rule_a_trunk_cancelled_counts_as_landed(self, bare_remote):
        """규칙A_cancelled도_착륙으로_본다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_trunk(a, "cancelled")
        self._push_session_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.holders == []
        assert [s.reason for s in result.skipped] == ["trunk_cancelled"]

    def test_rule_b_trunk_itself_cannot_be_holder(self, bare_remote):
        """규칙B_트렁크_자신은_홀더가_될_수_없다"""
        # main의 in_progress는 활성 claim이 아니라 대장 위생 실패(done 미기입 머지)다
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_trunk(a, "in_progress", "claude/dead-session")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.status == "ok"
        assert result.holders == []
        assert [(s.branch, s.reason) for s in result.skipped] == [("main", "trunk_not_session")]

    def test_rule_b_does_not_erase_real_session_claims(self, bare_remote):
        """규칙B는_실_세션_claim까지_지우지는_않는다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_trunk(a, "in_progress", "claude/dead-session")
        self._push_session_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert [h.branch for h in result.holders] == ["claude/session-a"]  # 살아있는 claim은 남는다
        assert [s.branch for s in result.skipped] == ["main"]

    def test_missing_trunk_task_file_falls_back_to_holder_check(self, bare_remote):
        """트렁크에_태스크_파일이_없으면_규칙A_신호없이_홀더검사"""
        # 브랜치에서 신설된 태스크 — 트렁크 사본이 없다고 stale로 오해하면 안 된다
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_session_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.trunk_status == ""
        assert [h.branch for h in result.holders] == ["claude/session-a"]

    def _break_ls_remote(self, monkeypatch):
        """원격 HEAD 조회만 실패시킨다 (fetch·show는 진짜)."""
        original = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv and argv[0] == "ls-remote":
                return subprocess.CompletedProcess(
                    ["git", *argv],
                    128,
                    stdout="",
                    stderr="fatal: unable to access origin: HTTP 403",
                )
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)

    def test_trunk_ref_queries_remote_head_first(self, bare_remote):
        """트렁크_ref는_원격_HEAD를_먼저_묻는다"""
        _, clone = bare_remote
        b = clone("session-b")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.trunk_source == "ls-remote"  # 하드코딩 아님·원격 권위 우선
        assert result.trunk_ref == "refs/remotes/origin/main"

    def test_stale_local_origin_head_defers_to_remote_authority(self, bare_remote):
        """로컬_origin_HEAD가_stale이어도_원격_권위를_따른다

        실측 사고 재현(2026-07-27): 로컬 origin/HEAD가 *세션 브랜치*를 가리킨 클론.

        그 값을 트렁크로 믿으면 규칙 A가 남의 세션 브랜치 status를 권위로 삼아
        보호를 조용히 꺼버린다(미탐). 원격 HEAD가 이겨야 한다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_trunk(a, "todo")  # 진짜 트렁크: 미착륙
        self._push_session_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        self._push_session_branch(a, "claude/liar", "done", None)  # 착륙했다고 주장하는 사본
        self._run(b, "fetch", "--quiet", "origin", "+refs/heads/*:refs/remotes/origin/*")
        self._run(b, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/claude/liar")
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.trunk_ref == "refs/remotes/origin/main"
        assert result.trunk_status == "todo"
        assert [h.branch for h in result.holders] == ["claude/session-a"]  # 보호 유지

    def test_blocked_remote_head_query_falls_back_to_local_symbolic_ref(
        self, bare_remote, monkeypatch
    ):
        """원격_HEAD_조회가_막히면_로컬_symbolic_ref로_폴백"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_trunk(a, "done")
        self._push_session_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        self._break_ls_remote(monkeypatch)
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.trunk_source == "symbolic-ref"
        assert result.holders == []  # 규칙 A는 그대로 작동

    def test_all_resolution_failure_falls_back_to_main(self, bare_remote, monkeypatch):
        """해소_전부_실패하면_main으로_폴백한다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_trunk(a, "done")
        self._push_session_branch(a, "claude/session-a", "in_progress", "claude/session-a")
        self._run(b, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        self._break_ls_remote(monkeypatch)
        result = remote_claims.scan_remote_in_progress(b, TASK, "claude/session-b")
        assert result.trunk_source == "fallback"
        assert result.trunk_ref == "refs/remotes/origin/main"
        assert result.holders == []


class TestStaleAndReap:
    def test_stale_triple_criteria(self):
        """stale_3중_기준 + task_missing_recent 4번째 사유(HARN-21)"""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
        fresh_ts = "2026-07-16T10:00:00Z"  # 2시간 전 — TTL(72h) 이내
        old_ts = "2026-07-10T10:00:00Z"  # 6일 전 — TTL 초과
        claims = [
            remote_claims.RemoteClaim(TASK, "sha1", "claude/a", fresh_ts),
            remote_claims.RemoteClaim("S1-02-done-task", "sha2", "claude/b", fresh_ts),
            remote_claims.RemoteClaim("S1-03-ghost-task", "sha3", "claude/c", fresh_ts),
            remote_claims.RemoteClaim("S1-04-old-task", "sha4", "claude/d", old_ts),
            # HARN-21 신규 — 오래된 missing claim(진짜 정리 대상)과
            # ts 없는 missing claim(나이 불명 → 보수적 보류) 두 축 추가.
            remote_claims.RemoteClaim("S1-05-old-ghost-task", "sha5", "claude/e", old_ts),
            remote_claims.RemoteClaim("S1-06-no-ts-ghost-task", "sha6", "claude/f", ""),
        ]
        backlog = _mk_backlog()
        backlog.tasks["S1-02-done-task"] = Task(
            id="S1-02-done-task",
            title="완료됨",
            track="math-completion",
            stage="S1",
            status="done",
            artifacts=["PR#1"],
        )
        backlog.tasks["S1-04-old-task"] = Task(
            id="S1-04-old-task",
            title="오래됨",
            track="math-completion",
            stage="S1",
            status="in_progress",
            session="claude/d",
        )
        stale = remote_claims.stale_claims(claims, backlog, ttl_hours=72, now=now)
        reasons = {c.task_id: reason for c, reason in stale}
        assert TASK not in reasons  # 신선 + in_progress → 유지
        assert reasons["S1-02-done-task"] == "task_done"  # 로컬 이미 done
        # HARN-21 결함③ 수정: 신선한 missing claim은 "task_missing"이 아니라
        # "task_missing_recent"(경합 조건 가능성 — 즉시 삭제 금지).
        assert reasons["S1-03-ghost-task"] == "task_missing_recent"
        assert reasons["S1-04-old-task"] == "ttl"  # TTL 초과
        assert reasons["S1-05-old-ghost-task"] == "task_missing"  # 오래된 missing은 여전히 정리
        assert reasons["S1-06-no-ts-ghost-task"] == "task_missing_recent"  # ts 없음 = 보수적 보류

    def test_reap_dry_run_does_not_delete(self, bare_remote, monkeypatch):
        """reap_dry_run은_삭제하지_않는다 — 오래된(TTL 초과) claim 기준"""
        _, clone = bare_remote
        a = clone("session-a")
        old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: old_ts)
        assert remote_claims.claim(a, "S1-03-ghost-task", "claude/session-a").status == "ok"
        later_now = old_ts + timedelta(hours=200)  # TTL(72h) 초과 — 진짜 stale
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: later_now)
        backlog = _mk_backlog()  # ghost-task 미포함 + 오래됨 → task_missing
        reaped, status, warnings = remote_claims.reap(a, backlog, ttl_hours=72, dry_run=True)
        assert status == "ok"
        assert len(reaped) == 1 and "task_missing" in reaped[0]
        assert "task_missing_recent" not in reaped[0]
        assert warnings == []
        claims, _ = remote_claims.list_claims(a)
        assert len(claims) == 1  # dry-run — 아직 남아 있음

    def test_reap_apply_actually_deletes(self, bare_remote, monkeypatch):
        """reap_apply는_실제_삭제 — 오래된(TTL 초과) claim 기준"""
        _, clone = bare_remote
        a = clone("session-a")
        old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: old_ts)
        assert remote_claims.claim(a, "S1-03-ghost-task", "claude/session-a").status == "ok"
        later_now = old_ts + timedelta(hours=200)  # TTL(72h) 초과 — 진짜 stale
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: later_now)
        backlog = _mk_backlog()
        reaped, status, warnings = remote_claims.reap(a, backlog, ttl_hours=72, dry_run=False)
        assert status == "ok" and len(reaped) == 1
        assert warnings == []
        claims, _ = remote_claims.list_claims(a)
        assert claims == []

    def test_query_failure_not_disguised_as_no_stale(self, bare_remote, monkeypatch):
        """조회_실패는_stale_없음으로_위장되지_않는다

        HARN-09 — 이 구분이 없어서 CI 교차검증이 공전했다.

        구 구현은 조회 실패 시 빈 목록만 돌려줬고, 호출자는 그것을 "stale 없음"과
        구별할 수 없었다. 인프라가 죽으면 "측정 실패"가 보여야지 "0건 통과"로
        위장되면 안 된다(CLAUDE.md AI·신뢰).
        """
        _, clone = bare_remote
        a = clone("session-a")
        assert remote_claims.claim(a, "S1-03-ghost-task", "claude/session-a").status == "ok"
        original = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv and argv[0] == "ls-remote":
                return subprocess.CompletedProcess(
                    argv, 128, stdout="", stderr="fatal: unable to access 'origin'"
                )
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        reaped, status, warnings = remote_claims.reap(a, _mk_backlog(), ttl_hours=72, dry_run=True)
        assert reaped == []
        assert warnings == []
        assert status != "ok", "조회 실패가 ok로 보고되면 '0건 통과' 위장이 된다"


class TestBranchGoneCriterion:
    """HARN-26 — 홀더 브랜치가 origin에 없는 claim 판정.

    실측 동기(2026-08-11): 대장 5건 중 3건이 존재하지 않는 브랜치를 홀더로 지목해
    새 세션의 착수를 막고 있었다. 기존 3중 기준(ttl·task_done·task_missing)에는
    이 축이 없어 TTL 72시간이 지나기 전에는 아무도 그 상태를 판정할 수 없었다.
    """

    NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    OLD = "2026-08-09T12:00:00Z"  # 48시간 전 — grace(24h) 초과, TTL(72h) 이내
    FRESH = "2026-08-11T10:00:00Z"  # 2시간 전 — grace 이내

    def _claims(self, ts: str, branch: str = "claude/a"):
        return [remote_claims.RemoteClaim(TASK, "sha1", branch, ts)]

    def _stale(self, claims, branches, **kw):
        return {
            c.task_id: reason
            for c, reason in remote_claims.stale_claims(
                claims, _mk_backlog(), 72, self.NOW, existing_branches=branches, **kw
            )
        }

    def test_missing_branch_past_grace_is_branch_gone(self):
        """홀더_브랜치_부재_유예초과는_branch_gone"""
        assert self._stale(self._claims(self.OLD), frozenset({"main"}))[TASK] == "branch_gone"

    def test_live_branch_is_never_stale(self):
        """홀더_브랜치_생존시_stale_아님 — 무차별 판정 방어(음성 대조)

        이 케이스가 없으면 "모든 claim을 branch_gone으로 친다"는 버그가 통과한다.
        나머지 케이스는 전부 '부재'만 다루므로 그 버그에 대해 변별력이 없다.
        """
        assert self._stale(self._claims(self.OLD), frozenset({"main", "claude/a"})) == {}

    def test_missing_branch_within_grace_is_recent(self):
        """유예_이내_부재는_branch_gone_recent — start 직후 첫 push 전 구간 보호"""
        assert self._stale(self._claims(self.FRESH), frozenset({"main"}))[TASK] == (
            "branch_gone_recent"
        )

    def test_unknown_age_defers_to_recent(self):
        """ts_없는_claim은_나이_불명이므로_유예 — '모른다'를 '오래됐다'로 반올림 금지"""
        assert self._stale(self._claims(""), frozenset({"main"}))[TASK] == "branch_gone_recent"

    def test_empty_branch_meta_is_never_branch_gone(self):
        """홀더_미상(메타_파손)은_branch_gone_아님 — 특정 불가와 소멸은 다르다"""
        assert TASK not in self._stale(self._claims(self.OLD, branch=""), frozenset({"main"}))

    def test_none_branches_suspends_criterion_but_keeps_others(self):
        """브랜치_집합_None이면_이_기준만_보류되고_TTL은_그대로_작동

        조회 실패로 얻은 빈 집합을 '브랜치 전멸'로 읽으면 대장을 통째로 지운다.
        동시에, 한 축의 보류가 나머지 판정까지 멈추게 해서도 안 된다.
        """
        very_old = [remote_claims.RemoteClaim(TASK, "sha1", "claude/a", "2026-08-01T12:00:00Z")]
        assert self._stale(very_old, None)[TASK] == "ttl"  # 10일 전 — TTL 초과
        assert TASK not in self._stale(self._claims(self.OLD), None)  # 48h — TTL 이내

    def test_branch_gone_takes_precedence_over_ttl(self):
        """둘_다_해당하면_branch_gone이_이긴다 — 자동 청소 대상 분류를 고정한다

        순서가 뒤집히면 사유가 `ttl`이 되고, ttl은 확정 신호가 아니라 자동 집행
        대상에서 빠진다(살아 있는 장기 세션일 수 있으므로). 즉 순서는 표시 문구가
        아니라 집행 여부를 바꾼다.
        """
        ancient = [remote_claims.RemoteClaim(TASK, "sha1", "claude/a", "2026-08-01T12:00:00Z")]
        assert self._stale(ancient, frozenset({"main"}))[TASK] == "branch_gone"

    def test_task_done_takes_precedence_over_branch_gone(self):
        """로컬이_이미_done이면_task_done이_이긴다"""
        backlog = _mk_backlog(status="done", session=None)
        backlog.tasks[TASK].artifacts = ["PR#1"]
        stale = remote_claims.stale_claims(
            self._claims(self.OLD), backlog, 72, self.NOW, existing_branches=frozenset({"main"})
        )
        assert [reason for _, reason in stale] == ["task_done"]


class TestRemoteBranchListing:
    """HARN-26 — `list_remote_branches`는 '조회 실패'와 '브랜치 없음'을 구분해야 한다."""

    def test_lists_pushed_branches(self, bare_remote):
        """푸시된_브랜치가_목록에_나온다"""
        _, clone = bare_remote
        a = clone("session-a")
        subprocess.run(["git", "push", "origin", "claude/session-a"], cwd=a, check=True)
        branches, status = remote_claims.list_remote_branches(a)
        assert status == "ok"
        assert branches is not None and {"main", "claude/session-a"} <= branches

    def test_unpushed_branch_absent(self, bare_remote):
        """체크아웃만_한_브랜치는_원격에_없다 — branch_gone 판정의 입력 전제"""
        _, clone = bare_remote
        a = clone("session-a")
        branches, status = remote_claims.list_remote_branches(a)
        assert status == "ok"
        assert branches is not None and "claude/session-a" not in branches

    def test_query_failure_returns_none_not_empty_set(self, bare_remote, monkeypatch):
        """조회_실패는_None — 빈_집합과_구별된다

        빈 집합을 돌려주면 호출부가 "원격에 브랜치가 하나도 없다"로 읽어
        살아 있는 claim을 전부 branch_gone으로 친다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        original = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv[:2] == ("ls-remote", "--heads"):
                return subprocess.CompletedProcess(
                    argv, 128, stdout="", stderr="fatal: unable to access 'origin'"
                )
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        branches, status = remote_claims.list_remote_branches(a)
        assert branches is None
        assert status != "ok"

    def test_empty_output_is_error_not_all_gone(self, bare_remote, monkeypatch):
        """rc0_빈_출력은_error — 정상 저장소에서 브랜치 0개는 나올 수 없다"""
        _, clone = bare_remote
        a = clone("session-a")
        original = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv[:2] == ("ls-remote", "--heads"):
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        branches, status = remote_claims.list_remote_branches(a)
        assert branches is None and status == "error"


class TestReapBranchGoneIntegration:
    """HARN-26 집행 지점 — `reap`이 실제로 이 기준을 경유하는가(계약이 아니라 배선)."""

    def test_reap_deletes_claim_whose_branch_vanished(self, bare_remote, monkeypatch):
        """홀더_브랜치가_사라진_claim은_reap이_삭제한다"""
        _, clone = bare_remote
        a = clone("session-a")
        created = datetime(2026, 8, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created)
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        # 48시간 뒤 — grace(24h) 초과이나 TTL(72h)에는 못 미친다. 즉 이 삭제는
        # 오직 branch_gone 기준으로만 성립한다(ttl이 대신 잡아준 게 아님).
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created + timedelta(hours=48))
        reaped, status, _ = remote_claims.reap(a, _mk_backlog(), ttl_hours=72, dry_run=False)
        assert status == "ok"
        assert len(reaped) == 1 and "branch_gone" in reaped[0]
        claims, _ = remote_claims.list_claims(a)
        assert claims == []

    def test_reap_keeps_claim_whose_branch_is_alive(self, bare_remote, monkeypatch):
        """홀더_브랜치가_살아있으면_reap이_보존한다 — 음성 대조

        위 테스트와 유일하게 다른 조건이 '브랜치를 push했는가'다. 무차별 삭제
        회귀가 생기면 이쪽만 RED가 된다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        subprocess.run(["git", "push", "origin", "claude/session-a"], cwd=a, check=True)
        created = datetime(2026, 8, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created)
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created + timedelta(hours=48))
        reaped, status, _ = remote_claims.reap(a, _mk_backlog(), ttl_hours=72, dry_run=False)
        assert status == "ok" and reaped == []
        claims, _ = remote_claims.list_claims(a)
        assert [c.task_id for c in claims] == [TASK]

    def test_branch_query_failure_preserves_claims_and_warns(self, bare_remote, monkeypatch):
        """브랜치_조회_실패시_claim은_보존되고_그_사실이_경고로_드러난다

        **이 테스트가 HARN-26의 최대 위험을 막는다.** 조회 실패를 '전부 부재'로
        읽으면 대장이 통째로 지워진다. 동시에 판정을 건너뛴 사실이 침묵되면
        "stale 없음"과 "판정 안 함"이 같은 화면이 된다(CLAUDE.md 침묵 실패 금지).

        주의: `--heads`만 실패시킨다. `ls-remote` 전체를 죽이면 `_fetch_claims_branch`가
        먼저 죽어 reap이 `status != ok`로 조기 반환하고, 그러면 이 테스트는
        '브랜치 판정 보류'가 아니라 이미 다른 테스트가 덮는 'claim 조회 실패'를
        검증하게 되어 아무것도 증명하지 못한다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        created = datetime(2026, 8, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created)
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created + timedelta(hours=48))
        original = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv[:2] == ("ls-remote", "--heads"):
                return subprocess.CompletedProcess(
                    argv, 128, stdout="", stderr="fatal: unable to access 'origin'"
                )
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        reaped, status, warnings = remote_claims.reap(a, _mk_backlog(), ttl_hours=72, dry_run=False)
        assert status == "ok", "claim 조회 자체는 성공했다 — 실패한 것은 브랜치 조회뿐"
        assert reaped == [], "판정 불가 상태에서 삭제가 일어나면 안 된다"
        assert any("홀더 브랜치 조회 불가" in w for w in warnings), "판정을 건너뛴 사실이 침묵됐다"
        claims, _ = remote_claims.list_claims(a)
        assert [c.task_id for c in claims] == [TASK]


class TestReapReasonFilter:
    """HARN-27 — 자동 청소는 확정 사유만 지운다. 걸러진 건은 버리지 않고 경고로 올린다."""

    def test_auto_reap_reasons_contains_only_confirmed_signals(self):
        """자동_청소_사유_집합_동결 — 이것이 안전 범위의 유일한 잠금장치다

        `ttl`은 살아 있는 장기 세션일 수 있고(실측 max 지속 66.4h로 TTL 72h에 근접),
        `task_missing`은 CI 러너가 main만 보기 때문에 다른 브랜치에서 등재된 태스크를
        구조적으로 '없음'으로 본다(HARN-15 비가시 부채 맹점). 둘 다 자동 삭제 부적합.
        """
        assert remote_claims.AUTO_REAP_REASONS == frozenset({"task_done", "branch_gone"})

    def test_filter_limits_deletion_and_preserves_others(self, bare_remote, monkeypatch):
        """확정_사유만_삭제되고_나머지는_원격에_남는다

        `task_done`(확정) 1건과 `ttl`(비확정) 1건을 동시에 두고 `--auto` 상당 호출을
        한다. 필터가 없으면 둘 다 사라져 RED가 된다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        subprocess.run(["git", "push", "origin", "claude/session-a"], cwd=a, check=True)
        created = datetime(2026, 8, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created)
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        assert remote_claims.claim(a, "S1-09-ttl-task", "claude/session-a").status == "ok"

        backlog = _mk_backlog(status="done", session=None)
        backlog.tasks[TASK].artifacts = ["PR#1"]
        backlog.tasks["S1-09-ttl-task"] = Task(
            id="S1-09-ttl-task",
            title="장기 세션",
            track="math-completion",
            stage="S1",
            status="in_progress",
            session="claude/session-a",
        )
        # TTL(72h) 초과 시점 — 브랜치는 살아 있으므로 branch_gone은 성립하지 않는다.
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created + timedelta(hours=200))
        reaped, status, warnings = remote_claims.reap(
            a,
            backlog,
            ttl_hours=72,
            dry_run=False,
            reasons=remote_claims.AUTO_REAP_REASONS,
        )
        assert status == "ok"
        assert len(reaped) == 1 and "task_done" in reaped[0]
        remaining, _ = remote_claims.list_claims(a)
        assert [c.task_id for c in remaining] == [
            "S1-09-ttl-task"
        ], "확정 사유가 아닌 ttl claim이 자동 청소로 사라졌다 — 살아 있는 장기 세션을 지운다"
        assert any(
            "자동 청소 제외" in w and "ttl" in w for w in warnings
        ), "걸러진 건이 조용히 버려졌다 — '지우지 않았다'가 보이지 않으면 침묵 실패다"

    def test_no_filter_deletes_everything_stale(self, bare_remote, monkeypatch):
        """필터_없으면_전_사유_삭제 — 사람이 치는 --apply의 기존 동작 보존(음성 대조)"""
        _, clone = bare_remote
        a = clone("session-a")
        subprocess.run(["git", "push", "origin", "claude/session-a"], cwd=a, check=True)
        created = datetime(2026, 8, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created)
        assert remote_claims.claim(a, TASK, "claude/session-a").status == "ok"
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: created + timedelta(hours=200))
        reaped, status, _ = remote_claims.reap(a, _mk_backlog(), ttl_hours=72, dry_run=False)
        assert status == "ok"
        assert len(reaped) == 1 and "ttl" in reaped[0]
        assert remote_claims.list_claims(a)[0] == []


class TestTaskMissingRecentRaceGuard:
    """HARN-21 결함③ — 신선한 missing claim은 reap에서 제외되고, 오래된 것은 여전히
    정리된다. 실제 `bare_remote`(진짜 로컬 원격)로 양방향(변별력)을 hermetic하게 검증.

    사고 시나리오: 세션 A가 add+start(claim)를 원격에 방금 반영했는데, 그 직후 세션 B가
    `claims reap --apply`를 돌리면 — B의 로컬 클론엔 A가 방금 추가한 태스크 파일이 아직
    없다(A가 아직 안 머지했으므로). `task is None`이 참이 되어 나이와 무관하게 즉시
    task_missing으로 지워지던 것이 구 버그다.
    """

    def test_freshly_created_claim_not_reaped_when_task_missing_locally(
        self, bare_remote, monkeypatch
    ):
        """방금_생성된_claim은_로컬에_태스크가_없어도_reap_안_됨"""
        _, clone = bare_remote
        a = clone("session-a")
        fixed_now = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: fixed_now)
        assert remote_claims.claim(a, "HARN-99-race-task", "claude/session-a").status == "ok"

        backlog = _mk_backlog()  # HARN-99-race-task 미포함 → A가 아직 안 머지한 상태 모사
        reaped, status, warnings = remote_claims.reap(a, backlog, ttl_hours=72, dry_run=False)
        assert status == "ok"
        assert reaped == [], "방금 생성된 claim이 task_missing으로 즉시 reap되면 안 된다"
        assert any(
            "HARN-99-race-task" in w and "task_missing_recent" in w for w in warnings
        ), "삭제하지 않되 경고로는 노출해야 한다(침묵 실패 금지)"
        claims, _ = remote_claims.list_claims(a)
        assert [c.task_id for c in claims] == ["HARN-99-race-task"], "claim이 살아있어야 한다"

    def test_old_claim_still_reaped_as_task_missing(self, bare_remote, monkeypatch):
        """오래된_claim은_여전히_task_missing으로_reap된다 — 변별력의 반대 축

        진짜 취소·삭제된 태스크의 잔존 claim을 정리하는 정상 기능은 유지해야 한다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        old_ts = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: old_ts)
        assert remote_claims.claim(a, "HARN-98-stale-task", "claude/session-a").status == "ok"

        later_now = old_ts + timedelta(hours=100)  # TTL(72h) 초과
        monkeypatch.setattr(remote_claims, "_utcnow", lambda: later_now)
        backlog = _mk_backlog()  # HARN-98-stale-task 미존재(진짜 삭제된 태스크 모사)
        reaped, status, warnings = remote_claims.reap(a, backlog, ttl_hours=72, dry_run=False)
        assert status == "ok"
        assert len(reaped) == 1
        assert "HARN-98-stale-task" in reaped[0] and "task_missing" in reaped[0]
        assert "task_missing_recent" not in reaped[0]
        assert warnings == []
        claims, _ = remote_claims.list_claims(a)
        assert claims == [], "오래된 claim은 실제로 삭제돼야 한다"


class TestScanStaleBranches:
    """장기 미머지 브랜치 감지 (HARN-13) — 진짜 로컬 원격에서 커밋 나이·ahead count 실측.

    2026-07-30 사고(claude/shadow-data-s3-pilot-nh5kbz 9일·40+커밋 고립)의 재발방지
    메커니즘. 변별력의 핵심은 "오래됐지만 이미 머지된 브랜치"와 "오래됐고 아직
    안 흡수된 브랜치"를 다른 값으로 구분하는가다 — 나이만 보고 ahead를 안 보면
    머지된 브랜치도 계속 stale로 오탐한다.
    """

    def _commit_backdated(self, repo: Path, days_ago: int, filename: str, message: str) -> None:
        """`days_ago`일 전 committerdate로 파일 1건을 커밋한다(나이 축 통제 실측용)."""
        (repo / filename).write_text(f"{message}\n", encoding="utf-8")
        past = datetime.now(timezone.utc) - timedelta(days=days_ago)
        iso = past.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        env = {
            "GIT_AUTHOR_DATE": iso,
            "GIT_COMMITTER_DATE": iso,
        }
        subprocess.run(["git", "add", filename], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo,
            check=True,
            capture_output=True,
            env={**_os_environ(), **env},
        )

    def test_detects_old_and_ahead_branch(self, bare_remote):
        """오래되고_ahead인_브랜치를_감지한다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        subprocess.run(
            ["git", "checkout", "-b", "claude/old-orphan"], cwd=a, check=True, capture_output=True
        )
        self._commit_backdated(a, days_ago=9, filename="orphan.txt", message="orphan work")
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/old-orphan"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        result = remote_claims.scan_stale_branches(b, days_threshold=3)
        assert result.status == "ok"
        branches = {s.branch: s for s in result.stale}
        assert "claude/old-orphan" in branches
        assert branches["claude/old-orphan"].ahead >= 1
        assert branches["claude/old-orphan"].age_days >= 9
        # 포팅 근거도 active claim도 PR 이력도 없으면 isolated (HARN-47 4분류).
        # bare 로컬 원격에는 refs/pull/*가 없으므로 조회는 *성공하고 0건*이다 — 즉
        # "PR로 노출된 적 없음"이 실제로 확인된 상태이지 미측정이 아니다.
        assert result.pr_lookup_ok is True
        assert branches["claude/old-orphan"].status == "isolated"
        assert branches["claude/old-orphan"].evidence == ""

    def test_recently_committed_branch_not_detected(self, bare_remote):
        """최근_커밋된_브랜치는_감지하지_않는다

        나이 조건 미충족 — ahead는 있지만 threshold 미만이면 stale이 아니다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        subprocess.run(
            ["git", "checkout", "-b", "claude/fresh"], cwd=a, check=True, capture_output=True
        )
        (a / "fresh.txt").write_text("fresh\n", encoding="utf-8")
        subprocess.run(["git", "add", "fresh.txt"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "fresh work"], cwd=a, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/fresh"], cwd=a, check=True, capture_output=True
        )
        result = remote_claims.scan_stale_branches(b, days_threshold=3)
        assert result.status == "ok"
        assert "claude/fresh" not in {s.branch for s in result.stale}

    def test_branch_absorbed_into_trunk_not_detected(self, bare_remote):
        """트렁크에_흡수된_브랜치는_감지하지_않는다

        ahead 조건 미충족 — 나이는 오래됐지만 트렁크가 이미 그 커밋을 포함하면 stale이 아니다.

        SQUASH 머지가 아니라 fast-forward로 트렁크에 실제로 흡수시켜, ahead count가
        정확히 0이 되는 경로를 재현한다(scan_remote_in_progress의 규칙 A·B와 동일하게
        조상 관계가 아니라 rev-list count로 판정하는 것을 검증).
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        subprocess.run(
            ["git", "checkout", "-b", "claude/landed"], cwd=a, check=True, capture_output=True
        )
        self._commit_backdated(a, days_ago=10, filename="landed.txt", message="landed work")
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/landed"], cwd=a, check=True, capture_output=True
        )
        # main으로 fast-forward 병합 후 push — 트렁크가 이 커밋을 실제로 흡수한다.
        subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            ["git", "merge", "--ff-only", "claude/landed"], cwd=a, check=True, capture_output=True
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=a, check=True, capture_output=True)

        result = remote_claims.scan_stale_branches(b, days_threshold=3)
        assert result.status == "ok"
        assert "claude/landed" not in {s.branch for s in result.stale}

    def test_trunk_with_porting_trace_classified_as_ported(self, bare_remote):
        """trunk에_포팅_흔적이_있으면_ported로_분류한다

        PR#705류 패턴("merge: ...(953m1e) 흡수") 재현 — 원본은 결정 대기가 아니다.

        2026-08-05 실측: SessionStart가 경고하던 19개 브랜치 중 10개가 이미 이 패턴으로
        trunk에 흡수된 뒤 원본만 방치돼 있었다 — unresolved와 뭉뚱그리면 Kiki가 매번
        이미 끝난 일까지 다시 훑어야 한다.

        2026-08-11 갱신: needle이 6자 세션 접미사에서 **브랜치 basename 전체**로 바뀌어
        커밋 메시지도 전체명을 인용하도록 고쳤다(6자 needle은 평범한 영단어까지 잡는
        오탐 생성기였다 — `_find_ported_evidence` docstring). 흡수 커밋이 `ported.txt`
        (원장 경로 밖)를 건드리는 것도 계약의 일부다 — 원장만 고친 커밋은 "언급"으로
        버려진다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-example-review-953m1e"
        subprocess.run(["git", "checkout", "-b", branch], cwd=a, check=True, capture_output=True)
        self._commit_backdated(a, days_ago=9, filename="orphan2.txt", message="review work")
        subprocess.run(
            ["git", "push", "-u", "origin", branch], cwd=a, check=True, capture_output=True
        )
        subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
        # HARN-37: 흡수 커밋은 브랜치의 고유 파일(orphan2.txt)을 실제로 옮겨야 한다.
        (a / "orphan2.txt").write_text("orphan2 content\n", encoding="utf-8")
        subprocess.run(["git", "add", "orphan2.txt"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"merge: {branch} 유용분 흡수"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=a, check=True, capture_output=True)

        result = remote_claims.scan_stale_branches(b, days_threshold=3)
        assert result.status == "ok"
        branches = {s.branch: s for s in result.stale}
        assert branch in branches
        assert branches[branch].status == "ported"
        assert "흡수" in branches[branch].evidence

    def test_remote_claimed_branch_classified_as_active(self, bare_remote):
        """원격_claim_중인_브랜치는_active로_분류한다

        다른 세션이 지금 이 브랜치에서 작업 중이면 방치가 아니라 진행 중인 정상 작업이다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-active-example-aaaaaa"
        subprocess.run(["git", "checkout", "-b", branch], cwd=a, check=True, capture_output=True)
        self._commit_backdated(a, days_ago=9, filename="active.txt", message="active work")
        subprocess.run(
            ["git", "push", "-u", "origin", branch], cwd=a, check=True, capture_output=True
        )

        result = remote_claims.scan_stale_branches(
            b, days_threshold=3, active_branches=frozenset({branch})
        )
        assert result.status == "ok"
        branches = {s.branch: s for s in result.stale}
        assert branch in branches
        assert branches[branch].status == "active"
        assert branches[branch].evidence == ""

    def test_four_classifications_distinguished_in_one_scan(self, bare_remote, monkeypatch):
        """네_분류가_한_스캔에서_동시에_구분된다

        isolated·pr_filed·ported·active가 서로 다른 값으로 동시에 나오는지 변별력 실측.

        각 분류가 개별 테스트에서만 통과하고 한 스캔에서는 서로를 오염시키면(예: 전부
        isolated로 뭉개짐) 실전에서 무의미하다 — 성공/실패에 같은 값을 내면 검증이
        아니라 위장(CLAUDE.md 변별력 없는 검증 스텝 금지).

        HARN-47이 추가한 pr_filed 축이 핵심이다. 이 축이 무력해지면(PR 대조 실패)
        11건이 통째로 isolated로 승격돼 "고립 7건"이라는 판정이 "고립 18건"이 된다 —
        경고 습관화가 정확히 그렇게 시작됐다.

        HARN-78: `_fetch_pr_states`를 "열림 확인됨"으로 고정한다 — 이 테스트의 초점은
        4분류(now 5분류) 자체지 열림/닫힘 정밀화가 아니고, 통제하지 않으면 이 스캔이
        도는 환경에 실제 `GITHUB_TOKEN`이 있는지에 따라 결과가 흔들린다(있으면 실제
        네트워크로 존재하지 않는 PR #77을 조회하려 들어 결정 불가능해진다).
        """
        monkeypatch.setattr(
            remote_claims, "_fetch_pr_states", lambda root, numbers: ({77: ("open", False)}, "")
        )
        _, clone = bare_remote
        remote_path, _ = bare_remote
        a, b = clone("session-a"), clone("session-b")

        isolated_branch = "claude/whymath-isolated-example-zzzzzz"
        pr_filed_branch = "claude/whymath-prfiled-example-yyyyyy"
        ported_branch = "claude/whymath-ported-example-953m1e"
        active_branch = "claude/whymath-active-example-bbbbbb"

        for branch, fname in [
            (isolated_branch, "u.txt"),
            (pr_filed_branch, "pr.txt"),
            (ported_branch, "p.txt"),
            (active_branch, "ac.txt"),
        ]:
            subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
            subprocess.run(
                ["git", "checkout", "-b", branch], cwd=a, check=True, capture_output=True
            )
            self._commit_backdated(a, days_ago=9, filename=fname, message=f"{branch} work")
            subprocess.run(
                ["git", "push", "-u", "origin", branch], cwd=a, check=True, capture_output=True
            )

        subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
        # HARN-37: 흡수 커밋은 ported_branch의 고유 파일(p.txt)을 실제로 착지시킨다.
        (a / "p.txt").write_text("ported\n", encoding="utf-8")
        subprocess.run(["git", "add", "p.txt"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            # needle은 브랜치 basename 전체다(2026-08-11) — 6자 접미사 인용으로는 안 잡힌다.
            ["git", "commit", "-m", f"merge: {ported_branch} 흡수"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=a, check=True, capture_output=True)

        # GitHub이 PR을 노출하는 방식 그대로 — 원격 bare 저장소에 refs/pull/<N>/head를
        # 만든다. 이 테스트가 실물 GitHub이 아니라 git 규약을 태우는 지점이다.
        pr_tip = subprocess.run(
            ["git", "rev-parse", f"refs/heads/{pr_filed_branch}"],
            cwd=a,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", "refs/pull/77/head", pr_tip],
            cwd=remote_path,
            check=True,
            capture_output=True,
        )

        result = remote_claims.scan_stale_branches(
            b, days_threshold=3, active_branches=frozenset({active_branch})
        )
        assert result.status == "ok"
        assert result.pr_lookup_ok is True
        branches = {s.branch: s for s in result.stale}
        assert branches[isolated_branch].status == "isolated"
        assert branches[pr_filed_branch].status == "pr_filed"
        assert branches[ported_branch].status == "ported"
        assert branches[active_branch].status == "active"
        # PR 번호가 실제로 실려야 브리핑이 사람에게 건넬 것이 생긴다 — 분류만 맞고
        # 번호가 비면 "PR 어딘가에 있음"이라는 쓸모없는 경고가 된다.
        assert branches[pr_filed_branch].evidence == "PR #77"

    def test_no_remote_is_offline_determination(self, git_repo: Path):
        """원격_없음은_offline_판정

        origin이 아예 없는 저장소 — '방치 브랜치 없음'이 아니라 offline이어야 한다.
        """
        result = remote_claims.scan_stale_branches(git_repo, days_threshold=3)
        assert result.status == "offline"
        assert result.stale == []

    # ────────────────────────────────────────────────────────────────────
    # 2026-08-11 결함 4종 봉인 — shallow 맹점 · 유령 ref · needle 오탐/미탐 · 인프라 브랜치
    # ────────────────────────────────────────────────────────────────────

    def _push_stale_branch(self, repo: Path, branch: str, filename: str) -> None:
        """9일 방치 브랜치 1건을 원격에 만든다(나이 임계 위)."""
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", branch], cwd=repo, check=True, capture_output=True)
        self._commit_backdated(repo, days_ago=9, filename=filename, message=f"{branch} work")
        subprocess.run(
            ["git", "push", "-u", "origin", branch], cwd=repo, check=True, capture_output=True
        )

    def _push_multifile_branch(self, repo: Path, branch: str, filenames: list[str]) -> None:
        """고유 코드 파일 여러 개를 가진 9일 방치 브랜치 — 부분 착지 판정의 재료."""
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", branch], cwd=repo, check=True, capture_output=True)
        for name in filenames:
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            self._commit_backdated(repo, days_ago=9, filename=name, message=f"{branch} {name}")
        subprocess.run(
            ["git", "push", "-u", "origin", branch], cwd=repo, check=True, capture_output=True
        )

    @staticmethod
    def _commit_on_main(repo: Path, files: dict[str, str], message: str) -> None:
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        for name, body in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            subprocess.run(["git", "add", name], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)

    def test_documenting_commit_is_not_porting_evidence(self, bare_remote):
        """문서화_커밋은_포팅_근거가_아니다 (HARN-37 ① 재현 고정)

        2026-08-30 브리핑이 `7n9n72`를 "이미 포팅됨(#770 근거)·결정 불요"로 분류했는데,
        실측은 main 부재 15파일 + 고유줄 수백이었다. **#770은 그 고립을 *실측·문서화*한
        커밋이지 포팅 커밋이 아니다** — 브랜치명을 인용하면서 (원장 밖) 자기 문서 파일을
        건드렸을 뿐인데 옛 판정은 그것을 흡수로 받았다.

        08-11 감사의 40xspg 오분류(문서 커밋을 근거로 2,153줄 삭제 직전)와 **동일 유형
        2회차**다. 여기서 위험한 오류는 미탐이 아니라 오탐이다 — "결정 불요" 라벨이
        실작업이 든 브랜치를 삭제 대상으로 만든다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/subject-problems-theory-check-7n9n72"
        self._push_multifile_branch(a, branch, ["src/mis.py", "tests/test_mis.py"])
        # 브랜치를 인용하며 **자기 조사 산출물만** 착지시킨 커밋(= #770 형태).
        # `reviews/`는 원장 최상위(docs)가 아니라 코드 취급이라 옛 필터를 그대로 통과했다.
        self._commit_on_main(
            a,
            {"reviews/stray_branch_audit.md": "이 브랜치들은 미해결이다\n"},
            f"조사: {branch} 고립 실측·문서화",
        )

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        entry = {s.branch: s for s in result.stale}[branch]
        assert entry.status != "ported", "문서화 커밋이 '결정 불요'를 만들면 고립이 숨는다"
        assert entry.evidence == ""
        assert entry.partial_port == ""  # 브랜치 파일을 하나도 옮기지 않았다

    def test_real_code_porting_stays_ported(self, bare_remote):
        """실코드를_옮긴_커밋은_계속_포팅됨이다 (HARN-37 ③ 대칭 축)

        위 강화가 *전건 미탐*으로 도망가면 브리핑이 다시 소음이 된다 — 40xspg(#801)처럼
        실제로 코드를 옮긴 커밋은 그대로 ported여야 한다. 한 방향만 검사하면 "아무것도
        ported로 부르지 않는" 구현도 통과한다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-solution-review-40xspg"
        self._push_multifile_branch(a, branch, ["src/sol.py", "tests/test_sol.py"])
        self._commit_on_main(
            a,
            {"src/sol.py": "sol\n", "tests/test_sol.py": "test\n"},
            f"S4-09: {branch} 실코드 회수",
        )

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        entry = {s.branch: s for s in result.stale}[branch]
        assert entry.status == "ported"
        assert "S4-09" in entry.evidence

    def test_partial_landing_is_not_ported_but_keeps_the_trace(self, bare_remote):
        """일부만_옮긴_커밋은_ported가_아니되_단서는_남는다

        전건 착지와 0건 착지 사이가 실제로 가장 흔한 상태다. 흡수 흔적을 **버리면** 사람이
        같은 조사를 다시 하고, **흡수로 단정하면** 잔여 고유 코드가 '결정 불요' 뒤에 숨는다.
        그래서 status는 ported가 아니고, 단서(N/M 파일)는 별도 필드로 싣는다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-partial-landing-abc123"
        self._push_multifile_branch(a, branch, ["src/one.py", "src/two.py", "src/three.py"])
        self._commit_on_main(a, {"src/one.py": "one\n"}, f"부분 회수: {branch} 중 일부")

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        entry = {s.branch: s for s in result.stale}[branch]
        assert entry.status != "ported"
        assert entry.partial_port.startswith("1/3 파일")
        assert "부분 회수" in entry.partial_port

    def test_multi_commit_recovery_unions_to_full_port(self, bare_remote):
        """여러_커밋에_나눠_회수해도_전건_착지로_본다 (#962 codex P2)

        회수는 종종 소형 PR 여럿으로 나뉜다 — 커밋 하나가 파일 A를, 다른 하나가 B를 옮긴다.
        각 커밋을 **따로** 재면 둘 다 부분 착지로 보여, 실제로는 전건 회수된 브랜치가 계속
        고립으로 남는다(과보고 → 경고 습관화). 근거 커밋들의 착지 파일을 합집합으로 본다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-split-recovery-def456"
        self._push_multifile_branch(a, branch, ["src/alpha.py", "src/beta.py"])
        self._commit_on_main(a, {"src/alpha.py": "alpha\n"}, f"1차 회수: {branch} 중 alpha")
        self._commit_on_main(a, {"src/beta.py": "beta\n"}, f"2차 회수: {branch} 중 beta")

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        entry = {s.branch: s for s in result.stale}[branch]
        assert entry.status == "ported", "합집합을 안 보면 전건 회수가 고립으로 남는다"
        assert "외 1건" in entry.evidence  # 기여 커밋이 복수임을 근거가 자인한다
        assert entry.partial_port == ""

    def test_failed_file_scan_is_indeterminate_not_full_port(self, bare_remote, monkeypatch):
        """분모_산출_실패는_전건_착지가_아니라_판정_불가다 (#962 codex P1)

        초판은 `git diff` 실패와 "코드 파일 없는 브랜치"를 같은 빈 집합으로 돌려줬다. 그러면
        호출부가 실패를 `0/0` 전건 착지로 읽어 **미검증 브랜치를 ported(= 삭제해도 안전)로
        표시**한다 — git이 잠깐 실패하는 것만으로 이 태스크가 막으려던 구멍이 그대로 다시
        열린다. 미측정을 0으로 바꾸지 않는다는 규칙이 정확히 이 자리다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-scan-failure-ghi789"
        self._push_multifile_branch(a, branch, ["src/gamma.py"])
        # 브랜치를 인용하며 **다른** 코드 파일을 건드린 커밋 — 옛 동작이라면 0/0 ported.
        self._commit_on_main(a, {"src/unrelated.py": "x\n"}, f"언급: {branch} 조사")

        real_git = remote_claims._git

        def flaky_diff(root, *argv, **kwargs):
            if argv[:2] == ("diff", "--name-only"):
                raise TimeoutError("git diff 타임아웃(합성)")
            return real_git(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", flaky_diff)
        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        entry = {s.branch: s for s in result.stale}[branch]
        assert entry.status != "ported", "판정 불가가 '결정 불요'가 되면 안 된다"
        assert entry.evidence == ""
        # 침묵 실패 금지 — 예외 타입명이 사유에 남는다.
        assert "TimeoutError" in entry.port_scan_error

    def test_shallow_clone_is_pending_not_ok(self, bare_remote, shallow_clone):
        """shallow_클론은_ok가_아니라_판정_보류다

        사고(2026-08-11): CCR 컨테이너 클론이 shallow였는데 스캐너가 그걸 모른 채
        판정해 브리핑 "미해결 19건" 중 10건을 오분류했다. 흡수 커밋이 절단면 밖이라
        grep이 못 본 것을 "포팅 근거 없음"과 같은 값으로 처리한 결과다.

        빈 목록을 '방치 없음'으로 읽으면 안 되는 것과 같은 이유로, *틀린* 목록을
        'ok'로 내보내서도 안 된다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        self._push_stale_branch(a, "claude/whymath-shallow-victim-example", "victim.txt")

        result = remote_claims.scan_stale_branches(shallow_clone("shallow-b"), days_threshold=3)

        assert result.status == "shallow"
        assert result.stale == []
        assert "--unshallow" in result.message

    def test_full_clone_still_detects_same_branch(self, bare_remote):
        """같은_저장소의_full_클론은_그_브랜치를_정상_검출한다

        위 테스트의 **음성 대조**. shallow 가드가 무차별 보류로 퍼지면(=어떤 클론에서도
        판정 안 함) 이 테스트가 실패한다 — 가드가 shallow에만 걸리는지 변별한다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_stale_branch(a, "claude/whymath-shallow-victim-example", "victim.txt")

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        assert result.status == "ok"
        assert "claude/whymath-shallow-victim-example" in {s.branch for s in result.stale}

    def test_shallow_guard_runs_before_fetch(self, shallow_clone, monkeypatch):
        """shallow_가드는_fetch보다_먼저_돈다

        어차피 못 믿을 결과를 위해 SessionStart마다 90초 예산의 전체 fetch를 물지
        않는다(fetch는 shallow를 해제하지도 못한다). 가드를 fetch 뒤로 옮기면 실패한다.
        """
        calls: list[tuple[str, ...]] = []
        real_git = remote_claims._git

        def spy(root, *argv: str, **kwargs):
            calls.append(argv)
            return real_git(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", spy)
        result = remote_claims.scan_stale_branches(shallow_clone("shallow-c"), days_threshold=3)

        assert result.status == "shallow"
        assert not [argv for argv in calls if argv and argv[0] == "fetch"]

    def test_deleted_upstream_branch_is_pruned(self, bare_remote):
        """원격에서_삭제된_브랜치는_스캔에서_사라진다

        사고(2026-08-11): fetch에 `--prune`이 없어 GitHub에서 이미 삭제된 브랜치의
        remote-tracking ref가 남았다. 스캐너는 그걸 "trunk 대비 N커밋 앞섬, Kiki 결정
        필요"로 계속 보고했지만 **결정할 대상이 존재하지 않았다**(실측 유령 23건).
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-ghost-branch-example"
        self._push_stale_branch(a, branch, "ghost.txt")

        # b가 한 번 관측해 remote-tracking ref를 캐시한 뒤, 원격에서 삭제한다.
        assert branch in {
            s.branch for s in remote_claims.scan_stale_branches(b, days_threshold=3).stale
        }
        subprocess.run(
            ["git", "push", "origin", "--delete", branch], cwd=a, check=True, capture_output=True
        )

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        assert result.status == "ok"
        assert branch not in {s.branch for s in result.stale}

    def test_claims_branch_never_reported_as_stale(self, bare_remote):
        """하네스_claim_브랜치는_결정_대기로_뜨지_않는다

        `harness-claims`는 하네스가 스스로 만드는 claim 저장소이지 사람이 결정할 작업
        브랜치가 아니다 — claim이 3일만 조용하면 "Kiki 결정 필요"로 뜨던 구멍을 막는다.
        정의상 대상 밖이라 만료 없는 유예에 해당하지 않는다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        subprocess.run(
            ["git", "checkout", "-b", remote_claims.CLAIMS_BRANCH],
            cwd=a,
            check=True,
            capture_output=True,
        )
        self._commit_backdated(a, days_ago=9, filename="claims.json", message="claim record")
        subprocess.run(
            ["git", "push", "-u", "origin", remote_claims.CLAIMS_BRANCH],
            cwd=a,
            check=True,
            capture_output=True,
        )

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        assert result.status == "ok"
        assert remote_claims.CLAIMS_BRANCH not in {s.branch for s in result.stale}

    def test_suffixless_branch_can_be_classified_ported(self, bare_remote):
        """6자_접미사가_없는_브랜치도_포팅_근거를_찾는다

        결함 ② 핵심. 옛 needle `-([a-z0-9]{6})$`는 세션 접미사가 없는 브랜치
        (`claude/harn-14-…`·`worktree-agent-…`)를 **시도조차 못 해** 항구적으로
        "미해결"에 남겼다. 실측: `worktree-agent-a6e26595b30efb856`은 PR #728로 이미
        포팅됐는데도 매 세션 결정 대기로 떴다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/harn-99-no-session-suffix-here"
        self._push_stale_branch(a, branch, "suffixless.txt")
        subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
        # HARN-37: 포팅 커밋은 **그 브랜치의 파일**을 착지시켜야 근거가 된다 —
        # 다른 파일을 건드린 커밋은 흡수가 아니라 언급이다.
        (a / "suffixless.txt").write_text("suffixless\n", encoding="utf-8")
        subprocess.run(["git", "add", "suffixless.txt"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            # 제목이 아니라 **본문**에 브랜치명을 인용한다(#728의 실제 패턴).
            ["git", "commit", "-m", "HARN-99: 고아 브랜치 회수", "-m", f"원본 = {branch}"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=a, check=True, capture_output=True)

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        branches = {s.branch: s for s in result.stale}
        assert branches[branch].status == "ported"
        assert "HARN-99" in branches[branch].evidence

    def test_ledger_only_mention_stays_unresolved(self, bare_remote):
        """원장만_고친_커밋의_언급은_포팅_근거가_아니다

        결함 ② 역방향(더 위험한 쪽). *"이 브랜치들은 미해결이다"*라고 적은 판정 문서
        커밋이 바로 그 브랜치를 "해결됨"으로 뒤집던 사고를 봉인한다.

        실측(2026-08-11): `claude/whymath-solution-review-40xspg`는 미회수 S4-09 완료분을
        안은 채 "이미 포팅됨 — 원본 정리만 필요, 결정 불요"로 분류돼 있었다. 근거로
        잡힌 커밋(`807aa479`)은 MEMORY.md·backlog·docs만 고친 판정 문서였다. 잘못된
        강등은 실작업이 든 브랜치를 삭제 대상으로 만든다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-solution-review-example"
        self._push_stale_branch(a, branch, "real_work.txt")
        subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
        (a / "docs").mkdir(exist_ok=True)
        (a / "docs" / "verdict.md").write_text(f"# 판정\n\n- {branch}: 미해결\n", encoding="utf-8")
        (a / "MEMORY.md").write_text("결정 로그\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"docs: 미머지 브랜치 판정 — {branch} 포함"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=a, check=True, capture_output=True)

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        branches = {s.branch: s for s in result.stale}
        # 요지는 "포팅됨으로 강등되지 않았다"이다. HARN-47 4분류에서 근거 없는 브랜치는
        # PR 이력까지 없으면 isolated다(bare 로컬 원격에는 refs/pull/*가 없다).
        assert branches[branch].status != "ported"
        assert branches[branch].status == "isolated"
        assert branches[branch].evidence == ""

    def test_common_word_suffix_does_not_match(self, bare_remote):
        """평범한_영단어_접미사는_근거로_잡히지_않는다

        옛 6자 needle의 오탐 회귀 봉인. `…-metrics-writer`의 "writer"가 무관한 커밋에
        매칭돼 그 브랜치를 "결정 불요"로 강등한 것이 실측됐다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/collab-99-learning-metrics-writer"
        self._push_stale_branch(a, branch, "metrics.txt")
        subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
        (a / "unrelated.py").write_text("writer = None\n", encoding="utf-8")
        subprocess.run(["git", "add", "unrelated.py"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "ASM-99: 무관한 writer 배선"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=a, check=True, capture_output=True)

        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        branches = {s.branch: s for s in result.stale}
        # 요지는 "포팅됨으로 강등되지 않았다"이다. HARN-47 4분류에서 근거 없는 브랜치는
        # PR 이력까지 없으면 isolated다(bare 로컬 원격에는 refs/pull/*가 없다).
        assert branches[branch].status != "ported"
        assert branches[branch].status == "isolated"

    def test_pr_lookup_failure_does_not_become_isolation_claim(self, bare_remote, monkeypatch):
        """PR_조회_실패는_고립_주장으로_바뀌지_않는다

        HARN-47에서 가장 위험한 오류는 미탐이 아니라 **오탐**이다. PR 대조가 실패했을
        때 그것을 "PR 이력 없음"으로 읽으면, 인프라가 죽은 순간 PR이 멀쩡히 열려 있는
        브랜치 전부가 "🔴 고립 — 회수 또는 삭제 필요"로 승격된다. 삭제를 유도하는 경보다.

        CLAUDE.md: 측정 실패와 통과는 같은 색이면 안 된다(이중 회계).
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = "claude/whymath-lookup-failure-example"
        self._push_stale_branch(a, branch, "work.txt")

        real_git = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv[:2] == ("ls-remote", "origin") and any("refs/pull/" in x for x in argv):
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="fatal: boom")
            return real_git(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        assert result.status == "ok"  # 스캔 자체는 성공 — PR 축만 미측정이다
        assert result.pr_lookup_ok is False
        branches = {s.branch: s for s in result.stale}
        assert branches[branch].status == "unresolved"
        assert branches[branch].status != "isolated"
        # 실패 사유가 남아야 한다 — 무타입 경고는 타임아웃·git 미설치·권한 오류를
        # 운영자에게 같은 글자로 보이게 만든다(Codex 리뷰 P1, 2026-08-31).
        assert result.pr_lookup_error, "PR 조회 실패 사유가 비었다 — 침묵 실패"
        assert "비0 종료" in result.pr_lookup_error

    def test_pr_lookup_exception_carries_type_name(self, bare_remote, monkeypatch):
        """PR_조회_예외는_타입명을_남긴다

        `TimeoutExpired`·`FileNotFoundError`·`OSError`가 전부 "PR 대조 실패"라는 같은
        글자로 뭉개지면 운영자는 무엇을 고쳐야 할지 알 수 없다. CLAUDE.md 침묵 실패
        금지는 예외 **타입명**을 로그에 남길 것을 요구한다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_stale_branch(a, "claude/whymath-exception-example", "w.txt")

        real_git = remote_claims._git

        def boom_git(root, *argv, **kwargs):
            if argv[:2] == ("ls-remote", "origin") and any("refs/pull/" in x for x in argv):
                raise FileNotFoundError("git 실행 파일 없음")
            return real_git(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", boom_git)
        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        assert result.status == "ok"
        assert result.pr_lookup_ok is False
        assert "FileNotFoundError" in result.pr_lookup_error

    def test_pr_lookup_timeout_carries_type_name(self, bare_remote, monkeypatch):
        """PR_조회_타임아웃도_타입명을_남긴다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._push_stale_branch(a, "claude/whymath-timeout-example", "w.txt")

        real_git = remote_claims._git

        def slow_git(root, *argv, **kwargs):
            if argv[:2] == ("ls-remote", "origin") and any("refs/pull/" in x for x in argv):
                raise subprocess.TimeoutExpired(cmd="git ls-remote", timeout=20)
            return real_git(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", slow_git)
        result = remote_claims.scan_stale_branches(b, days_threshold=3)

        assert result.pr_lookup_ok is False
        assert "TimeoutExpired" in result.pr_lookup_error

    def test_pr_lookup_uses_no_extra_git_call_per_branch(self, bare_remote):
        """PR_대조는_브랜치마다_원격_왕복을_추가하지_않는다

        SessionStart 훅은 매 세션 도는 경로다. 브랜치마다 ls-remote를 돌리면 원격
        왕복이 N배가 되어 예산을 넘긴다 — tip sha는 이미 도는 for-each-ref 열거에
        얹어 받는다. 이 계약이 깨지면(브랜치별 rev-parse/ls-remote 부활) 조용히
        느려지기만 하므로 기계로 붙든다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        for i in range(3):
            subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
            self._push_stale_branch(a, f"claude/whymath-budget-example-{i}", f"w{i}.txt")

        real_git = remote_claims._git
        ls_remote_calls: list[tuple[str, ...]] = []

        def counting_git(root, *argv, **kwargs):
            if argv and argv[0] in ("ls-remote", "rev-parse"):
                ls_remote_calls.append(argv)
            return real_git(root, *argv, **kwargs)

        monkeypatch_target = counting_git
        original = remote_claims._git
        remote_claims._git = monkeypatch_target  # type: ignore[assignment]
        try:
            result = remote_claims.scan_stale_branches(b, days_threshold=3)
        finally:
            remote_claims._git = original  # type: ignore[assignment]

        assert result.status == "ok"
        assert len([c for c in result.stale if c.status == "isolated"]) >= 3
        pr_ref_calls = [c for c in ls_remote_calls if any("refs/pull/" in x for x in c)]
        # 브랜치가 3건이어도 PR ref 조회는 스캔당 1회여야 한다.
        assert len(pr_ref_calls) == 1, f"PR ref 조회가 {len(pr_ref_calls)}회 — 스캔당 1회여야 한다"

    def test_short_branch_name_skips_evidence_lookup(self, bare_remote):
        """너무_짧은_브랜치명은_근거_조회를_건너뛴다

        짧은 needle은 우연 매칭 생성기다 — 길이 하한(12자) 아래면 grep 자체를 하지 않는다.
        """
        assert (
            remote_claims._find_ported_evidence(Path("."), "origin/main", "claude/ab").header == ""
        )

    def test_query_failure_not_disguised_as_empty_list(self, bare_remote, monkeypatch):
        """조회_실패는_빈_목록으로_위장되지_않는다

        fetch 실패가 '방치 브랜치 0건'과 같은 값이면 인프라 장애가 "문제 없음"으로 읽힌다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        original = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv and argv[0] == "fetch":
                return subprocess.CompletedProcess(
                    argv, 128, stdout="", stderr="fatal: unable to access 'origin'"
                )
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        result = remote_claims.scan_stale_branches(a, days_threshold=3)
        assert result.status != "ok"
        assert result.stale == []


class TestFetchPrStates:
    """`_fetch_pr_states` — GitHub API로 pr_filed 후보의 열림/닫힘·머지 여부를 가른다 (HARN-78).

    `_fetch_pr_head_shas`(오프라인 git)와 달리 이 함수는 네트워크 API가 **필수**다.
    토큰 없이 호출되면 즉시 `None`을 돌려줘야 한다(미인증 요청은 IP당 60req/h로
    상시 소진 상태 — CLAUDE.md 2026-09-01 main red 실측과 같은 함정).
    """

    def test_no_token_returns_none_without_network_call(self, tmp_path, monkeypatch):
        """토큰_없으면_네트워크를_아예_안_부르고_None을_돌려준다"""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        calls: list[list[str]] = []
        monkeypatch.setattr(
            remote_claims.subprocess,
            "run",
            lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0),
        )
        result, error = remote_claims._fetch_pr_states(tmp_path, [77])
        assert result is None
        assert "NoTokenError" in error
        assert calls == [], "토큰이 없는데 subprocess가 불렸다 — 조회를 시도해서는 안 된다"

    def test_empty_input_returns_empty_dict_without_network_call(self, tmp_path, monkeypatch):
        """조회_대상_0건이면_네트워크_없이_빈_dict를_돌려준다

        토큰 유무와 무관하게 성립해야 한다 — "조회할 게 없음"과 "조회 실패"는 다른 사실이다.
        """
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        calls: list[list[str]] = []
        monkeypatch.setattr(
            remote_claims.subprocess,
            "run",
            lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0),
        )
        result, error = remote_claims._fetch_pr_states(tmp_path, [])
        assert result == {}
        assert error == ""
        assert calls == []

    def test_success_distinguishes_open_and_closed_unmerged(self, tmp_path, monkeypatch):
        """성공하면_열림과_닫힘·미머지가_다른_값으로_나온다 — 변별력의 핵심"""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")

        def fake_git(root, *argv, **kwargs):
            assert argv[:2] == ("remote", "get-url")
            return subprocess.CompletedProcess(
                argv, 0, stdout="https://github.com/doldori7/WhyMath.git\n", stderr=""
            )

        payloads = {
            77: {"state": "open", "merged": False},
            967: {"state": "closed", "merged": False},
        }

        def fake_run(argv, **kwargs):
            assert argv[0] == "curl"
            number = int(argv[-1].rsplit("/", 1)[-1])
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(payloads[number]), stderr=""
            )

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        monkeypatch.setattr(remote_claims.subprocess, "run", fake_run)

        result, error = remote_claims._fetch_pr_states(tmp_path, [77, 967])
        assert error == ""
        assert result == {77: ("open", False), 967: ("closed", False)}

    def test_curl_exception_returns_none_with_exception_type(self, tmp_path, monkeypatch):
        """curl_호출_자체가_죽으면_예외_타입명을_담아_None을_돌려준다 (침묵 실패 금지)"""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")

        def fake_git(root, *argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0, stdout="https://github.com/doldori7/WhyMath.git\n", stderr=""
            )

        def boom(argv, **kwargs):
            raise OSError("curl 미설치")

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        monkeypatch.setattr(remote_claims.subprocess, "run", boom)

        result, error = remote_claims._fetch_pr_states(tmp_path, [77])
        assert result is None
        assert "OSError" in error

    def test_non_github_remote_returns_none(self, tmp_path, monkeypatch):
        """origin이_GitHub이_아니면_None — URL 파싱 실패도 침묵하지 않는다"""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")

        def fake_git(root, *argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0, stdout="https://gitlab.com/example/repo.git\n", stderr=""
            )

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        result, error = remote_claims._fetch_pr_states(tmp_path, [77])
        assert result is None
        assert "RemoteParseError" in error

    def test_scan_budget_stops_remaining_lookups(self, tmp_path, monkeypatch):
        """후보가_많아도_전체_예산을_넘기면_남은_조회를_건너뛰고_실패로_낸다 (Codex 리뷰, PR #1043).

        수정 전에는 후보 수만큼 순차 curl 호출이 무제한으로 누적돼, 후보가 많으면
        SessionStart 훅·CI 잡을 임의로 오래 묶어 둘 수 있었다. 예산을 0으로 낮춰
        "이미 예산을 다 썼다"를 흉내 내면, 첫 후보를 조회하기도 전에 멈춰야 한다
        (침묵 성공이 아니라 명시적 실패 사유를 낸다).
        """
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setattr(remote_claims, "_PR_STATE_SCAN_BUDGET_SECONDS", 0.0)

        def fake_git(root, *argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0, stdout="https://github.com/doldori7/WhyMath.git\n", stderr=""
            )

        calls: list[list[str]] = []
        monkeypatch.setattr(remote_claims, "_git", fake_git)
        monkeypatch.setattr(
            remote_claims.subprocess,
            "run",
            lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0),
        )

        result, error = remote_claims._fetch_pr_states(tmp_path, [77, 967])
        assert result is None
        assert "ScanBudgetExceededError" in error
        assert calls == [], "예산을 이미 초과했으면 curl을 한 번도 부르지 않아야 한다"


class TestPrStateReclassification:
    """`scan_stale_branches`가 `_fetch_pr_states`를 소비해 pr_filed를 정밀화한다 (HARN-78).

    `_fetch_pr_states` 내부(GitHub API)는 위 `TestFetchPrStates`가 이미 단위로 봉인했다 —
    여기서는 그 결과가 분류·evidence·`pr_state_lookup_ok`에 **정확히** 반영되는지만 본다.
    실물 GitHub API를 부르지 않도록 `_fetch_pr_states` 자체를 monkeypatch한다(bare 로컬
    원격은 github.com URL이 아니므로 그 아래 계층을 그대로 쓰면 매번 RemoteParseError다).
    """

    def _push_pr_filed_branch(self, bare_remote, pr_number: int) -> tuple[Path, str]:
        """pr_filed로 1차 분류될 브랜치 1건을 원격에 만들고 (clone, branch명)을 돌려준다."""
        remote_path, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        branch = f"claude/whymath-prstate-example-{pr_number}"
        subprocess.run(["git", "checkout", "-b", branch], cwd=a, check=True, capture_output=True)
        (a / "w.txt").write_text("work\n", encoding="utf-8")
        subprocess.run(["git", "add", "w.txt"], cwd=a, check=True, capture_output=True)
        past = (datetime.now(timezone.utc) - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        subprocess.run(
            ["git", "commit", "-m", "work"],
            cwd=a,
            check=True,
            capture_output=True,
            env={**_os_environ(), "GIT_AUTHOR_DATE": past, "GIT_COMMITTER_DATE": past},
        )
        subprocess.run(
            ["git", "push", "-u", "origin", branch], cwd=a, check=True, capture_output=True
        )
        tip = subprocess.run(
            ["git", "rev-parse", f"refs/heads/{branch}"],
            cwd=a,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", f"refs/pull/{pr_number}/head", tip],
            cwd=remote_path,
            check=True,
            capture_output=True,
        )
        return b, branch

    def test_closed_unmerged_pr_reclassified_as_pr_closed(self, bare_remote, monkeypatch):
        """닫히고_미머지된_PR은_pr_closed로_승격된다 — isolated와 같은 행동 요구

        재현 대상(HARN-78 acceptance ①): PR #967·#802·#675 전부 closed·merged=false인데
        `pr_filed`로 분류돼 "결정 불요"처럼 보였다.
        """
        b, branch = self._push_pr_filed_branch(bare_remote, 967)
        monkeypatch.setattr(
            remote_claims, "_fetch_pr_states", lambda root, numbers: ({967: ("closed", False)}, "")
        )
        result = remote_claims.scan_stale_branches(b, days_threshold=3)
        assert result.status == "ok"
        assert result.pr_state_lookup_ok is True
        branches = {s.branch: s for s in result.stale}
        assert branches[branch].status == "pr_closed"
        assert branches[branch].evidence == "PR #967 닫힘(미머지)"

    def test_open_pr_stays_pr_filed(self, bare_remote, monkeypatch):
        """열린_PR은_pr_filed로_남는다 — 처분은 그 PR에서 그대로 유효"""
        b, branch = self._push_pr_filed_branch(bare_remote, 975)
        monkeypatch.setattr(
            remote_claims, "_fetch_pr_states", lambda root, numbers: ({975: ("open", False)}, "")
        )
        result = remote_claims.scan_stale_branches(b, days_threshold=3)
        assert result.status == "ok"
        assert result.pr_state_lookup_ok is True
        branches = {s.branch: s for s in result.stale}
        assert branches[branch].status == "pr_filed"
        assert branches[branch].evidence == "PR #975"

    def test_lookup_failure_marks_evidence_unconfirmed_not_open(self, bare_remote, monkeypatch):
        """상태_조회_실패는_'열림'으로_가정하지_않고_'상태_미확인'을_명시한다

        성공(상태 확인됨)과 실패(미확인)가 다른 글자를 내야 한다(HARN-78 acceptance ③) —
        여기서 실패를 "그냥 pr_filed 그대로"로 조용히 두면 열림과 미확인이 같은 글자가 된다.
        """
        b, branch = self._push_pr_filed_branch(bare_remote, 802)
        monkeypatch.setattr(
            remote_claims,
            "_fetch_pr_states",
            lambda root, numbers: (None, "NoTokenError: GITHUB_TOKEN/GH_TOKEN 미설정"),
        )
        result = remote_claims.scan_stale_branches(b, days_threshold=3)
        assert result.status == "ok"
        assert result.pr_state_lookup_ok is False
        assert "NoTokenError" in result.pr_state_lookup_error
        branches = {s.branch: s for s in result.stale}
        assert branches[branch].status == "pr_filed"
        assert branches[branch].evidence == "PR #802 (상태 미확인)"

    def test_no_pr_filed_candidates_skips_lookup_entirely(self, bare_remote, monkeypatch):
        """pr_filed_후보가_0건이면_상태_조회_자체를_시도하지_않는다

        "조회 안 함"(대상 없음)과 "조회 실패"는 다른 사실이다 — 전자는 pr_state_lookup_ok가
        True(기본값)로 남아야 하고, `_fetch_pr_states`가 호출조차 되지 않아야 한다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        subprocess.run(
            ["git", "checkout", "-b", "claude/no-pr-here"], cwd=a, check=True, capture_output=True
        )
        past = (datetime.now(timezone.utc) - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        (a / "iso.txt").write_text("iso\n", encoding="utf-8")
        subprocess.run(["git", "add", "iso.txt"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "iso work"],
            cwd=a,
            check=True,
            capture_output=True,
            env={**_os_environ(), "GIT_AUTHOR_DATE": past, "GIT_COMMITTER_DATE": past},
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/no-pr-here"],
            cwd=a,
            check=True,
            capture_output=True,
        )

        called = False

        def boom(root, numbers):
            nonlocal called
            called = True
            return ({}, "")

        monkeypatch.setattr(remote_claims, "_fetch_pr_states", boom)
        result = remote_claims.scan_stale_branches(b, days_threshold=3)
        assert result.status == "ok"
        assert result.pr_state_lookup_ok is True
        assert result.pr_state_lookup_error == ""
        assert called is False, "pr_filed 후보가 없는데 상태 조회를 시도했다"
        assert {s.branch: s.status for s in result.stale}["claude/no-pr-here"] == "isolated"


class TestScanDocSeriesDuplicates:
    """설계 문서 중복 착수 탐지(HARN-14) — 나이 임계 없이 진짜 로컬 원격에서 실측.

    2026-08-04 사고(claude/whymath-operations-platform-cn6dxi 1일 경과·HARN-13의 3일
    나이 임계 아래라 브리핑에 안 뜸)의 재발방지. 변별력의 핵심은 "이미 SQUASH 머지돼
    트렁크에 실제로 존재하는 파일"과 "트렁크에 없는 진짜 신규 파일"을 다른 값으로
    구분하는가다 — 3점 diff(`A...B`)를 쓰면 전자도 오탐한다(SQUASH는 원 브랜치 커밋을
    트렁크의 조상으로 만들지 않아 merge-base가 머지 이전에 머무르기 때문).
    """

    def _add_doc(self, repo: Path, relpath: str, content: str = "content\n") -> None:
        path = repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", relpath], cwd=repo, check=True, capture_output=True)

    def test_new_design_doc_branch_detected_regardless_of_age(self, bare_remote):
        """새_설계문서를_추가한_브랜치를_나이_무관하게_감지한다

        방금(0일 전) 만든 브랜치도 즉시 잡혀야 한다 — 이 스캔은 나이 임계가 없다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._add_doc(a, "docs/architecture/foo_gap_review.md", "새 갭 리뷰\n")
        subprocess.run(
            ["git", "commit", "-m", "add foo gap review"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/session-a"],
            cwd=a,
            check=True,
            capture_output=True,
        )

        result = remote_claims.scan_doc_series_duplicates(b)
        assert result.status == "ok"
        branches = {c.branch: c for c in result.candidates}
        assert "claude/session-a" in branches
        assert branches["claude/session-a"].files == ("docs/architecture/foo_gap_review.md",)

    def test_non_doc_file_addition_not_detected(self, bare_remote):
        """문서가_아닌_파일_추가는_감지하지_않는다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._add_doc(a, "src/backend/whymath_backend/ops/foo.py", "# code\n")
        subprocess.run(
            ["git", "commit", "-m", "add unrelated code"], cwd=a, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/session-a"],
            cwd=a,
            check=True,
            capture_output=True,
        )

        result = remote_claims.scan_doc_series_duplicates(b)
        assert result.status == "ok"
        assert "claude/session-a" not in {c.branch for c in result.candidates}

    def test_non_review_suffix_under_docs_not_detected(self, bare_remote):
        """docs_안이어도_review_접미어가_아니면_감지하지_않는다"""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._add_doc(a, "docs/architecture/foo_notes.md", "무관 문서\n")
        subprocess.run(
            ["git", "commit", "-m", "add unrelated doc"], cwd=a, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/session-a"],
            cwd=a,
            check=True,
            capture_output=True,
        )

        result = remote_claims.scan_doc_series_duplicates(b)
        assert result.status == "ok"
        assert "claude/session-a" not in {c.branch for c in result.candidates}

    def test_already_squash_merged_doc_not_false_positive(self, bare_remote):
        """이미_SQUASH_머지된_문서는_오탐하지_않는다

        핵심 회귀 — 3점 diff였다면 이 케이스가 오탐났을 것(설계 중 실측으로 발견).

        브랜치가 신규 문서를 추가해 push한 뒤, 그 브랜치를 SQUASH(비-ff)로 main에
        합치고 origin/main을 갱신한다. 원 브랜치 ref는 원격에 그대로 남는다(GitHub가
        squash 머지 후 브랜치를 자동 삭제하지 않는 한 흔한 상태) — 이 상태에서 스캔이
        그 브랜치를 더 이상 후보로 잡으면 안 된다(파일이 이미 트렁크에 있으므로).
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._add_doc(a, "docs/architecture/landed_gap_review.md", "머지된 갭 리뷰\n")
        subprocess.run(
            ["git", "commit", "-m", "add landed gap review"], cwd=a, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/session-a"],
            cwd=a,
            check=True,
            capture_output=True,
        )

        # session-a에서 SQUASH 머지 시뮬레이션: main으로 체크아웃 후 --squash 병합·새 커밋.
        subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            ["git", "merge", "--squash", "claude/session-a"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "squash merge landed gap review"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=a, check=True, capture_output=True)

        result = remote_claims.scan_doc_series_duplicates(b)
        assert result.status == "ok"
        assert "claude/session-a" not in {
            c.branch for c in result.candidates
        }, "SQUASH 머지로 이미 트렁크에 존재하는 문서가 오탐됨 — 3점 diff 회귀 의심"

    def test_discriminates_unmerged_shown_then_merged_gone(self, bare_remote):
        """변별력_미머지일때_뜨고_머지후_사라진다

        ⑤ — 같은 브랜치가 미머지 상태와 머지 후 상태에서 실제로 다른 값을 낸다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        self._add_doc(a, "docs/architecture/roundtrip_gap_review.md", "왕복 갭 리뷰\n")
        subprocess.run(
            ["git", "commit", "-m", "add roundtrip gap review"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "claude/session-a"],
            cwd=a,
            check=True,
            capture_output=True,
        )

        before = remote_claims.scan_doc_series_duplicates(b)
        assert "claude/session-a" in {c.branch for c in before.candidates}  # 미머지 — 뜬다

        subprocess.run(["git", "checkout", "main"], cwd=a, check=True, capture_output=True)
        subprocess.run(
            ["git", "merge", "--squash", "claude/session-a"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "squash merge roundtrip"],
            cwd=a,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=a, check=True, capture_output=True)

        after = remote_claims.scan_doc_series_duplicates(b)
        assert "claude/session-a" not in {c.branch for c in after.candidates}  # 머지 후 — 사라진다

    def test_no_remote_is_offline_judgment(self, git_repo: Path):
        """원격_없음은_offline_판정"""
        result = remote_claims.scan_doc_series_duplicates(git_repo)
        assert result.status == "offline"
        assert result.candidates == []

    def test_query_failure_not_disguised_as_empty_list(self, bare_remote, monkeypatch):
        """조회_실패는_빈_목록으로_위장되지_않는다"""
        _, clone = bare_remote
        a = clone("session-a")
        original = remote_claims._git

        def fake_git(root, *argv, **kwargs):
            if argv and argv[0] == "fetch":
                return subprocess.CompletedProcess(
                    argv, 128, stdout="", stderr="fatal: unable to access 'origin'"
                )
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        result = remote_claims.scan_doc_series_duplicates(a)
        assert result.status != "ok"
        assert result.candidates == []


def _os_environ() -> dict[str, str]:
    import os

    return dict(os.environ)


class TestCrlfSanitization:
    """HARN-36 — claim 경로 CRLF 오염 차단·레거시 오염 인식.

    사고 경위: Windows 세션의 text 모드 stdin 개행 변환(\\n→\\r\\n)이 mktree 파일명에
    \\r를 넣어 harness-claims 트리에 "claims\\r/MISC-16.json\\r"가 실재했고, Linux
    세션의 경로 대조가 조용히 어긋나 활성 claim 보호가 무력해질 수 있었다.
    """

    def test_claim_with_cr_in_identifiers_writes_clean_path(self, bare_remote):
        """CR_주입_task_id·branch가_트리에서_깨끗한_경로로_기록된다 (변별력: 새니타이즈 제거 시 red)"""
        _, clone = bare_remote
        a = clone("session-a")
        result = remote_claims.claim(a, TASK + "\r", "claude/session-a\r\n")
        assert result.status == "ok"
        # 트리 실측 — 파싱(정규화 경유)이 아니라 원시 경로 바이트로 판정한다
        sha, status = remote_claims._fetch_claims_branch(a)
        assert status == "ok"
        ls = remote_claims._git(a, "ls-tree", "-r", "-z", sha)
        raw_paths = [e.partition("\t")[2] for e in ls.stdout.split("\0") if e.strip()]
        assert raw_paths == [f"claims/{TASK}.json"]
        assert all("\r" not in p and "\n" not in p for p in raw_paths)
        # 메타의 branch에도 개행이 없다
        claims, _ = remote_claims.list_claims(a, with_meta=True)
        assert claims[0].branch == "claude/session-a"

    def test_read_claims_recognizes_legacy_cr_polluted_tree(self, bare_remote):
        """구버전_오염_트리(claims\\r/X.json\\r)도_활성_claim으로_인식된다"""
        _, clone = bare_remote
        a = clone("session-a")
        # 오염 트리를 직접 제작 — mktree에 바이트로 \r 포함 파일명을 밀어 넣는다
        payload = '{"branch": "claude/other", "task": "%s", "ts": "2026-08-25T00:00:00Z"}' % TASK
        blob = remote_claims._git(a, "hash-object", "-w", "--stdin", input_text=payload)
        assert blob.returncode == 0
        sub = remote_claims._git(
            a, "mktree", input_text=f"100644 blob {blob.stdout.strip()}\t{TASK}.json\r\n"
        )
        assert sub.returncode == 0
        root_tree = remote_claims._git(
            a, "mktree", input_text=f"040000 tree {sub.stdout.strip()}\tclaims\r\n"
        )
        assert root_tree.returncode == 0
        commit = remote_claims._git(
            a,
            "commit-tree",
            root_tree.stdout.strip(),
            "-m",
            "polluted",
            env_extra=remote_claims._COMMIT_IDENTITY,
        )
        assert commit.returncode == 0
        # 오염 상태 확인(전제): 원시 경로에 \r가 실재한다
        ls = remote_claims._git(a, "ls-tree", "-r", "-z", commit.stdout.strip())
        assert "\r" in ls.stdout
        # 정규화 읽기 — task_id가 깨끗하게 인식된다 (이 줄이 수정 전 코드에서 red)
        claims = remote_claims._read_claims(a, commit.stdout.strip())
        assert [c.task_id for c in claims] == [TASK]
        assert claims[0].branch == "claude/other"

    def test_git_stdin_is_bytes_never_text(self, monkeypatch, tmp_path):
        """_git의_stdin은_바이트다 — text 모드 개행 변환이 구조적으로 불가능함을 동결"""
        captured: dict = {}
        real_run = subprocess.run

        def spy(argv, **kwargs):
            captured.update(kwargs)
            return real_run(argv, **kwargs)

        monkeypatch.setattr(remote_claims.subprocess, "run", spy)
        result = remote_claims._git(tmp_path, "version", input_text="a\nb\n")
        assert result.returncode == 0
        assert isinstance(captured.get("input"), bytes)  # str이면 Windows에서 \n→\r\n
        assert "encoding" not in captured  # encoding 지정 = text 모드 stdin의 입구


class TestProxyBlockedAttribution:
    """정책 거부를 "응답 형식 이상"으로 오귀속하지 않는다 (HARN-04).

    왜 이 테스트가 있나 — 프록시가 막은 응답도 `{"message": ...}` 모양이라 기존
    `"state" not in data` 분기에 함께 떨어졌고, 거기 붙은 문구가 "응답 형식 이상"이었다.
    형식 결함(우리 코드가 고칠 것)과 환경 차단(이 세션에서 못 고칠 것)은 처방이 정반대인데
    한 글자로 보였고, 그래서 **같은 조사가 세 세션 반복**됐다(2026-09-11·09-12 ×2 비재현
    기록이 태스크 acceptance에 쌓여 있다).

    각 절마다 *그 절이 없으면 통과해 버리는* 입력을 픽스처로 둔다 — 그리고 마지막 두 건은
    **대조군**이다: 진짜 형식 이상은 여전히 형식 이상으로 남아야 하고(과잉 수정 방지),
    정상 응답은 아무 영향도 받지 않아야 한다.
    """

    _NUMERIC = {
        "message": (
            "Numeric-ID repository paths (repositories/{id}/...) are not supported "
            "through this proxy. Use repos/{owner}/{repo}/..."
        )
    }
    _SCOPE = {
        "message": (
            "GitHub access to this repository is not enabled for this session. "
            "Use the add_repo tool."
        )
    }

    def test_numeric_path_rejection_is_attributed_not_called_malformed(self):
        """숫자경로_거부는_전용_사유로_귀속된다 — '형식 이상'이 아니다"""
        reason = remote_claims._attribute_api_failure(self._NUMERIC)
        assert reason is not None
        assert reason.startswith("ProxyNumericPathBlocked")
        assert "형식" not in reason

    def test_numeric_path_reason_says_renaming_does_not_help(self):
        """이름을_고치면_된다고_말하지_않는다 — 실측이 반대이기 때문

        2026-09-12 실측: 정본 이름(`kiki-s-broom/WhyMath`)은 리다이렉트 없이 '세션 미활성'
        403을 받는다. 즉 origin 이름을 바꾸면 실패 *문구*만 바뀌고 조회는 그대로 실패한다.
        이 단언이 없으면 미래의 누군가가 친절한 마음으로 "origin을 정본으로 바꾸세요"를
        넣게 되고, 그건 태스크 acceptance ④가 이름 붙인 함정 그 자체다.
        """
        reason = remote_claims._attribute_api_failure(self._NUMERIC)
        assert reason is not None and "뚫리지 않는다" in reason
        # 주장만 있고 근거가 없으면 다음 세션이 그것을 믿을지 말지 판단할 수 없다 —
        # 그래서 *실측했다는 사실 자체*도 문면에 남는지 본다. 이 단언이 없으면 근거 절만
        # 지우는 변경이 조용히 통과한다(뮤테이션 M3 생존으로 실제로 확인하고 추가했다).
        assert (
            "실측" in reason
        ), "판정 근거(실측) 표기가 사라졌다 — 주장만 남으면 재검증이 불가능하다"

    def test_session_scope_rejection_is_attributed_separately(self):
        """세션_미활성은_숫자경로와_다른_사유로_갈린다 — 둘을 한 글자로 뭉치지 않는다"""
        reason = remote_claims._attribute_api_failure(self._SCOPE)
        assert reason is not None
        assert reason.startswith("SessionScopeBlocked")

    def test_genuinely_malformed_payload_keeps_the_shape_error(self):
        """[대조군] 진짜_형식_이상은_여전히_None을_돌려준다 — 과잉 수정 방지

        이 대조군이 없으면 "무엇이든 정책 거부로 귀속"이라는 과잉 수정이 통과한다.
        그러면 우리 코드의 진짜 결함이 '환경 탓'으로 위장된다.
        """
        assert remote_claims._attribute_api_failure({"unexpected": "payload"}) is None
        assert remote_claims._attribute_api_failure([1, 2, 3]) is None
        assert remote_claims._attribute_api_failure({"message": 42}) is None

    def test_unrelated_api_message_is_not_swallowed(self):
        """[대조군] 다른_message는_귀속하지_않는다 — rate limit·404를 정책 거부로 접지 않는다"""
        assert remote_claims._attribute_api_failure({"message": "Not Found"}) is None
        assert remote_claims._attribute_api_failure({"message": "API rate limit exceeded"}) is None

    def test_state_lookup_surfaces_the_attributed_reason(self, tmp_path, monkeypatch):
        """[집행 지점] `_fetch_pr_states`가 실제로 그 사유를 낸다 — 계약만 두지 않는다"""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setattr(
            remote_claims,
            "_git",
            lambda root, *a, **k: subprocess.CompletedProcess(
                a, 0, stdout="https://github.com/doldori7/WhyMath.git\n", stderr=""
            ),
        )
        monkeypatch.setattr(
            remote_claims.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(self._NUMERIC), stderr=""
            ),
        )
        result, error = remote_claims._fetch_pr_states(tmp_path, [675])
        assert result is None
        assert "ProxyNumericPathBlocked" in error and "#675" in error

    def test_label_lookup_surfaces_the_attributed_reason(self, tmp_path, monkeypatch):
        """[집행 지점] 라벨_조회도_같은_귀속을_낸다 — 한쪽만 고치면 다른 쪽이 조사를 재생산한다"""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setattr(
            remote_claims,
            "_git",
            lambda root, *a, **k: subprocess.CompletedProcess(
                a, 0, stdout="https://github.com/doldori7/WhyMath.git\n", stderr=""
            ),
        )
        monkeypatch.setattr(
            remote_claims.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(self._SCOPE), stderr=""
            ),
        )
        result, error = remote_claims._fetch_pr_labels(tmp_path, [675])
        assert result is None
        assert "SessionScopeBlocked" in error and "#675" in error
