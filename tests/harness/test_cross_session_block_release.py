"""HARN-134 — 차단 홀드의 **교차 세션 해제**. HARN-48 ④의 미이행 축 승계.

배경: `HARN-48-block-remote-hold-publication`(done) acceptance ④가 "unblock이 홀드를
해제 — 안 걷으면 해제된 태스크가 영구 차단으로 보인다"를 약속했고, 그 구현
(`test_block_hold_cross_session.py::TestUnblockReleasesHold`)은 **같은 세션이 block하고
같은 세션이 unblock하는 경로만** 덮었다. `cmd_unblock`은 `_release_remote_claim`에
`task.session`을 넘기는데 `cmd_block`이 그 필드를 비우므로 항상 `current_branch`로
폴백한다 — 즉 **차단을 건 세션이 그대로 살아 있을 때만** 홀더 브랜치가 일치한다.

그런데 차단 사유는 대부분 외부 입력·사람 판정 대기라, **해소를 판정하는 쪽은 거의 항상
다음 세션**이다. 즉 ④가 실제로 보호하는 경우가 오히려 드문 쪽이었다. 실측(2026-09-22):
`EOS-128`의 홀드를 다른 브랜치에서 걷으려다 `'…'의 claim — 강제 해제는 --force 필수`로
막혀, 정상 절차가 *탈취용 탈출구*를 쓰게 만드는 상태였고 Kiki 왕복 1회를 썼다.

이 파일이 계약으로 동결하는 것 (acceptance ①~④):
  ① 재현·해소 — 홀더가 아닌 세션이 `unblock`으로 차단 홀드를 정상 경로로 걷는다.
  ② kind 경계 — `claim`(착수 점유)은 여전히 막힌다. 열린 것은 `block`뿐이다.
     **kind는 호출자의 가정이 아니라 실제 홀더 레코드에서 읽는다.**
  ③ 실패 주입 3종 — 홀더 브랜치 생존 / 홀더 브랜치 소멸 / 원격 조회 실패.
     특히 조회 실패를 "홀드 없음"으로 읽지 않는다.
  ④ 침묵 금지 — 해제 실패 시 로컬 전이를 **하지 않는다**. 종전은 경고 1줄 뒤
     로컬만 todo로 바꿔 "대장은 차단 · 로컬은 todo"인 분기가 무증상으로 남았다.

**변별력 설계**: 성공 방향만 재면 "항상 연다"는 구현(= `--force` 상시 적용)도 통과한다.
그래서 ②의 대조군(claim은 막힌다)과 ③의 조회 실패 대조군(offline은 통과·error는 거부)을
같은 파일에 둔다. offline과 error를 한 색으로 접으면 둘 중 하나가 반드시 틀린다 —
원격이 아예 없으면 교차 세션 채널 자체가 없어 분기할 상태가 없지만, 조회만 실패한
경우에는 홀드가 살아 있어 다른 세션의 start가 계속 거부된다.
"""

from __future__ import annotations

from pathlib import Path

import remote_claims
import store

import backlog as cli

TASK = "T1-02-cross-session-hold"


def _seed(path: Path, monkeypatch) -> None:
    monkeypatch.chdir(path)
    assert cli.main(["seed"]) == 0


def _add(task_id: str = TASK) -> int:
    return cli.main(
        [
            "add",
            "--eos-priority",
            "P2",
            "--id",
            task_id,
            "--track",
            "math-completion",
            "--stage",
            "S1",
            "--title",
            "HARN-134 교차 세션 홀드 해제 대상",
        ]
    )


def _adopt_blocked(repo: Path, task_id: str = TASK) -> None:
    """ "main에서 차단 상태를 받아온 다음 세션"을 모사한다.

    왜 store로 주입하는가: 이 상태를 CLI로 만들려면 B가 스스로 `block`을 불러야 하는데,
    그러면 B 자신이 홀더가 돼 **재현하려는 불일치가 사라진다**(홀더 브랜치 == 현재
    브랜치). 실제 상황에서 B는 A가 머지한 YAML을 pull로 받을 뿐이므로, B의 로컬은
    `status=blocked` · `session=None`이다 — 그 `None`이 `prev_session or current_branch`
    폴백을 B의 브랜치로 만들고, 그것이 홀더(A)와 어긋나는 것이 이 결함의 기전이다.
    """
    backlog, _ = store.load_backlog(repo)
    task = backlog.tasks[task_id]
    task.status = "blocked"
    task.session = None
    store.save_task(repo, task)


def _held(repo: Path):
    claims, status = remote_claims.list_claims(repo, with_meta=True)
    assert status == "ok", f"원격 대장 조회 실패({status}) — 이 단언은 상태를 무시하지 않는다"
    return [c for c in claims if c.task_id == TASK]


def _task_bytes(repo: Path, task_id: str = TASK) -> bytes:
    return (repo / "backlog" / "tasks" / f"{task_id}.yaml").read_bytes()


class TestForeignSessionCanReleaseBlockHold:
    """① 재현·해소 — 홀더가 아닌 세션이 정상 경로로 걷는다."""

    def test_other_session_unblocks_and_hold_disappears(self, bare_remote, monkeypatch):
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")

        _seed(a, monkeypatch)
        assert _add() == 0
        assert cli.main(["block", TASK, "--reason", "Kiki 입력 대기"]) == 0
        assert _held(a)[0].kind == "block"

        _seed(b, monkeypatch)
        assert _add() == 0
        _adopt_blocked(b)
        # 홀더(A)의 브랜치는 **살아 있다** — ③의 첫 주입이다. 생존 자체가 block
        # 홀드의 해제를 막아서는 안 된다(막으면 차단이 영구가 된다).
        assert cli.main(["unblock", TASK]) == 0
        assert _held(b) == [], "홀더가 아닌 세션의 unblock이 홀드를 못 걷었다"

        # 걷힌 뒤에는 그 세션이 그대로 착수할 수 있어야 한다 — 해제의 목적이 그것이다
        assert cli.main(["start", TASK]) == 0

    def test_holder_branch_deleted_still_releases(self, bare_remote, monkeypatch):
        """③ 두 번째 주입 — 홀더 브랜치가 이미 사라진(머지 후 삭제) 경우."""
        import subprocess

        bare, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")

        _seed(a, monkeypatch)
        assert _add() == 0
        assert cli.main(["block", TASK, "--reason", "외부 회신 대기"]) == 0
        subprocess.run(
            ["git", "push", "origin", "HEAD:refs/heads/claude/session-a"],
            cwd=a,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "push", "origin", "--delete", "claude/session-a"],
            cwd=a,
            capture_output=True,
            check=True,
        )

        _seed(b, monkeypatch)
        assert _add() == 0
        _adopt_blocked(b)
        assert cli.main(["unblock", TASK]) == 0
        assert _held(b) == []


class TestClaimKindStaysProtected:
    """② kind 경계 — 열린 것은 block뿐이다. 이 반대 방향이 없으면 '항상 연다'도 통과한다."""

    def test_foreign_claim_release_still_refused(self, bare_remote, monkeypatch):
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _seed(a, monkeypatch)
        assert _add() == 0
        assert cli.main(["start", TASK]) == 0  # 착수 점유(kind=claim)
        assert _held(a)[0].kind == "claim"

        # block을 허용해도 claim은 막힌다 — 판정이 **실제 레코드의 kind**로 나기 때문이다.
        result = remote_claims.release(b, TASK, "claude/session-b", allow_foreign_kinds=("block",))
        assert result.status == "error"
        assert "--force" in result.message
        assert _held(a)[0].kind == "claim", "거부했는데 레코드가 지워졌다"

    def test_force_still_opens_everything(self, bare_remote, monkeypatch):
        """탈출구는 그대로 남는다 — 이 항이 없으면 위 거부가 복구 불능 상태를 만든다."""
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _seed(a, monkeypatch)
        assert _add() == 0
        assert cli.main(["start", TASK]) == 0
        assert remote_claims.release(b, TASK, "claude/session-b", force=True).status == "ok"
        assert _held(b) == []

    def test_holder_releasing_own_claim_still_succeeds(self, bare_remote, monkeypatch):
        """`foreign` 절의 반례 — **홀더 자신**의 해제는 kind와 무관하게 통과한다.

        이 픽스처가 없으면 `foreign = True`(항상 불일치로 본다) 뮤테이션이 살아남는다.
        위 두 테스트는 전부 *불일치* 방향이라 그 절을 한 번도 밟지 않기 때문이다 —
        절을 하나 둘 때마다 "이 절이 없으면 무엇이 통과하는가"의 반례를 픽스처에 둔다.
        """
        _, clone = bare_remote
        a = clone("session-a")
        _seed(a, monkeypatch)
        assert _add() == 0
        assert cli.main(["start", TASK]) == 0
        assert _held(a)[0].branch == "claude/session-a"
        # 같은 브랜치가 부르므로 홀더 불일치가 아니다 — allow 목록도 force도 없이 통과
        assert remote_claims.release(a, TASK, "claude/session-a").status == "ok"
        assert _held(a) == []

    def test_default_call_site_is_unchanged(self, bare_remote, monkeypatch):
        """기본값 변별력 — 인자를 안 주면 block 홀드도 종전대로 막혀야 한다.

        이 항이 없으면 `allow_foreign_kinds`의 기본값이 실수로 `("block",)`이 돼도
        아무도 모른다. 기본값은 "아무것도 열지 않음"이어야 하고, 여는 것은 호출부의
        **명시적 결정**이다.
        """
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _seed(a, monkeypatch)
        assert _add() == 0
        assert cli.main(["block", TASK, "--reason", "대기"]) == 0
        assert remote_claims.release(b, TASK, "claude/session-b").status == "error"
        assert _held(a)[0].kind == "block"


class TestRemoteLookupFailureIsNotSilence:
    """③ 세 번째 주입 + ④ — 조회 실패를 '홀드 없음'으로 읽지 않는다."""

    def test_lookup_error_refuses_and_leaves_task_blocked(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _seed(a, monkeypatch)
        assert _add() == 0
        assert cli.main(["block", TASK, "--reason", "대기"]) == 0

        _seed(b, monkeypatch)
        assert _add() == 0
        _adopt_blocked(b)
        before = _task_bytes(b)

        # 원격 조회 경계에 실패를 주입한다 — release 본체는 그대로 돈다.
        monkeypatch.setattr(remote_claims, "_fetch_claims_branch", lambda root: ("", "error"))
        capsys.readouterr()
        assert cli.main(["unblock", TASK]) == 1, "조회 실패를 '홀드 없음'으로 읽었다"
        err = capsys.readouterr().err
        assert "차단 해제를 중단" in err
        assert "blocked 그대로" in err

        # ④ 분기 상태가 생기지 않았는가 — 파일이 **바이트 동일**해야 한다
        assert _task_bytes(b) == before
        backlog, _ = store.load_backlog(b)
        assert backlog.tasks[TASK].status == "blocked"

    def test_offline_repo_unblock_proceeds(self, git_repo: Path, monkeypatch):
        """대조군 — origin이 아예 없으면 통과한다.

        offline과 error를 한 색으로 접으면 둘 중 하나가 반드시 틀린다. 원격이 없는
        저장소에는 교차 세션 채널 자체가 없어 분기할 상태가 없지만, 조회만 실패한
        경우에는 홀드가 살아 있어 다른 세션의 start가 계속 거부된다.
        """
        monkeypatch.chdir(git_repo)
        assert cli.main(["seed"]) == 0
        assert _add() == 0
        assert cli.main(["block", TASK, "--reason", "오프라인 차단"]) == 0
        assert cli.main(["unblock", TASK]) == 0
        backlog, _ = store.load_backlog(git_repo)
        assert backlog.tasks[TASK].status == "todo"

    def test_release_status_is_recorded_in_the_event(self, bare_remote, monkeypatch):
        """성공도 근거를 남긴다 — 화면은 휘발하고 대장은 남는다."""
        import json

        _, clone = bare_remote
        a, b = clone("session-a"), clone("session-b")
        _seed(a, monkeypatch)
        assert _add() == 0
        assert cli.main(["block", TASK, "--reason", "대기"]) == 0
        _seed(b, monkeypatch)
        assert _add() == 0
        _adopt_blocked(b)
        assert cli.main(["unblock", TASK]) == 0

        rows = [
            json.loads(line)
            for path in store.event_paths(b)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        unblocks = [r for r in rows if r.get("action") == "unblock" and r.get("id") == TASK]
        assert len(unblocks) == 1
        assert unblocks[-1]["release_status"] == "ok"
