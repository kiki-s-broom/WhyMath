"""backlog.py add — 원격 브랜치 backlog/tasks/ 파일명 교차 스캔 (HARN-15).

HARN-10 가드(`cmd_add`의 `<PREFIX>-<번호>` 충돌 검사, `tests/harness/test_cli.py`의
`TestIdNumberCollision`)의 3회차 결함 교정이다. 기존 가드는 로컬 백로그 + 원격
claim 대장(harness-claims 브랜치, **in_progress로 claim된 태스크만** 기록)만 본다.
그래서 "다른 브랜치에 이미 backlog/tasks/<ID>.yaml로 **등재만 되고 아직 착수(claim)
되지 않은** 번호"는 claim 대장에 원천적으로 안 잡힌다 — OPS-17·OPS-18이 main과
미머지 브랜치에 각각 다른 슬러그로 이중 등재된 사고(2026-08-03)가 정확히 이 맹점이다.

이 파일은 그 맹점을 메우는 `remote_claims.scan_remote_task_files` 배선을
`backlog.py add`(CLI 종단)에서 검증한다. 진짜 로컬 원격(bare repo, `bare_remote`
픽스처)에서 실제 git push/fetch/ls-tree로 검증한다 — 시임(가짜 monkeypatch)이 아니다.

변별력(양방향, acceptance ③):
    ① 타 브랜치의 backlog/tasks/에만 존재하는 번호로 add → 거부 + 다음 빈 번호 제안
    ② 그 브랜치의 remote-tracking ref가 없는 상태에서는 → 통과
두 결과가 갈리는 것 자체가 "번호를 실제로 원격 브랜치에서 읽어서 판정한다"는 증거다.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import number_guard
import remote_claims
import store

import backlog as cli


def _age_branch_stamp(repo: Path, seconds: float) -> None:
    """전체 브랜치 fetch 스탬프(HARN-111 ⑦(다))를 `seconds`초 전으로 기록한다."""
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    path = Path(common) if Path(common).is_absolute() else repo / common
    (path / number_guard.STAMP_FILE).write_text(
        json.dumps({"ts": moment.strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8"
    )


def _fail_heads_fetch(monkeypatch) -> None:
    """전체 브랜치 갱신(ⓓ)만 네트워크 실패로 만든다 — claim fetch·예약 push는 그대로 둔다.

    git 계층에서 주입하는 이유: 갱신 함수 자체를 바꿔치기하면 실패 분류(`_classify_failure`)와
    경고 조립 경로를 태우지 못한다.
    """
    real = remote_claims._git

    def fake(root, *argv, **kw):
        if argv and argv[0] == "fetch" and number_guard.HEADS_REFSPEC in argv:
            return subprocess.CompletedProcess(
                ["git", *argv],
                128,
                stdout="",
                stderr="fatal: unable to access 'https://example.invalid/x.git/': "
                "Could not resolve host: example.invalid\n",
            )
        return real(root, *argv, **kw)

    monkeypatch.setattr(remote_claims, "_git", fake)


class TestCrossBranchTaskFileNumberCollision:
    """원격 브랜치의 backlog/tasks/ 파일명만으로 존재하는 번호 충돌."""

    def _add(self, task_id: str, title: str = "교차 브랜치 번호 충돌 테스트") -> int:
        return cli.main(
            [
                "add",
                "--eos-priority",
                "P2",
                "--id",
                task_id,
                "--title",
                title,
                "--track",
                "math-completion",
                "--stage",
                "S2",
            ]
        )

    def _push_branch(self, repo: Path, branch: str) -> None:
        for argv in (
            ["checkout", "-q", "-B", branch],
            ["add", "."],
            ["commit", "-q", "-m", "등재만 하고 claim은 하지 않은 상태"],
            ["push", "--quiet", "-u", "origin", branch],
        ):
            subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)

    def _seed_other_branch_with_task(self, clone, monkeypatch, task_id: str) -> Path:
        """`other` 세션이 태스크를 add만 하고(claim 없이) 브랜치를 push한 상태를 만든다.

        HARN-111 이후 `add`는 번호를 원격에 **예약**한다(ⓐ). 이 클래스가 재는 것은 *파일명
        스캔 출처*이므로 예약을 남기지 않는 세션(구버전 하네스·예약 실패)을 모사한다 — 예약
        출처가 먼저 잡으면 파일명 스캔이 일하는지를 이 테스트로 알 수 없다.
        """
        other = clone("other")
        monkeypatch.chdir(other)
        assert cli.main(["seed"]) == 0
        with monkeypatch.context() as patch:
            patch.setattr(
                number_guard, "reserve", lambda *a, **k: number_guard.ReserveResult("skipped")
            )
            assert self._add(task_id) == 0  # 이 시점엔 other 자신의 로컬 백로그라 충돌 없음
        self._push_branch(other, "claude/other")
        return other

    def test_number_registered_only_in_other_branch_task_file_rejected(
        self, bare_remote, monkeypatch, capsys
    ):
        """다른_브랜치_backlog_tasks_파일명만_있는_번호도_거부되고_다음_빈번호_제안"""
        _, clone = bare_remote
        self._seed_other_branch_with_task(clone, monkeypatch, "S9-50-other-branch-task")

        # newcomer는 other의 push *이후* clone하므로, git clone의 기본 refspec이
        # refs/remotes/origin/claude/other를 이미 캐시해 둔다 — 이 테스트는 이후
        # 별도 fetch를 걸지 않는다(= scan_remote_task_files가 실제로 fetch 없이
        # 캐시된 ref만으로 판정함을 증명한다).
        newcomer = clone("newcomer")
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0

        capsys.readouterr()  # 셋업 출력을 버리고 add 출력만 본다
        assert self._add("S9-50-my-slug") == 1, "번호 충돌은 거부돼야 한다"
        captured = capsys.readouterr()
        assert "S9-50" in captured.err
        assert "원격 브랜치 backlog/tasks/" in captured.err, "새 출처 라벨이 노출돼야 한다"
        assert "claude/other" in captured.err, "어느 브랜치가 점유했는지 밝혀야 한다"
        assert "S9-51" in captured.err, "다음 빈 번호가 제안돼야 한다"

        backlog, _ = store.load_backlog(newcomer)
        assert "S9-50-my-slug" not in backlog.tasks

    def test_branch_tracking_ref_removed_is_refetched_and_rejected(
        self, bare_remote, monkeypatch, capsys
    ):
        """이_클론에_ref가_없는_원격_브랜치도_add가_다시_받아_거부한다 (HARN-111 ⓓ · EOS-128)

        **이 테스트는 종전 계약을 뒤집는다.** HARN-15 판은 "ref가 없으면 통과"를 변별력의
        반대쪽 축으로 동결했는데, 그 상태가 바로 4회차 사고(2026-09-20 EOS-128)였다 — 선착
        브랜치가 19분 먼저 origin에 있었지만 이 클론에 remote-tracking ref가 없어 0건으로
        보였고, 0건은 '없음'과 같은 색이었다. 이제 `add`는 스캔 직전에 `+refs/heads/*`를
        갱신하므로 같은 상태에서 **거부**가 맞다. 반대쪽 축(진짜로 없는 브랜치 → 통과)은
        아래 `test_branch_deleted_on_origin_is_pruned_and_add_passes`가 맡는다.
        """
        _, clone = bare_remote
        self._seed_other_branch_with_task(clone, monkeypatch, "S9-60-other-branch-task")

        newcomer = clone("newcomer")
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0

        # remote-tracking ref 자체를 지운다 — "이 브랜치를 본 적 없는 클론"(좁은 CCR 클론) 재현.
        subprocess.run(
            ["git", "update-ref", "-d", "refs/remotes/origin/claude/other"],
            cwd=newcomer,
            check=True,
            capture_output=True,
        )
        # 전제 확인(변별력): 갱신 없는 스캔은 정말로 그 브랜치를 못 본다 — 종전 경로의 실패 재현
        files, status = remote_claims.scan_remote_task_files(newcomer)
        assert status == "ok"
        assert not [f for f in files if f.branch == "claude/other"], "전제가 깨졌다 — 무효 테스트"

        capsys.readouterr()
        assert self._add("S9-60-my-slug") == 1, "origin에 있는 번호를 캐시 부재로 놓치면 안 된다"
        err = capsys.readouterr().err
        assert "원격 브랜치 backlog/tasks/(claude/other)" in err
        assert "S9-61" in err, "다음 빈 번호 제안(재선택)이 있어야 한다"
        backlog, _ = store.load_backlog(newcomer)
        assert "S9-60-my-slug" not in backlog.tasks

    def test_branch_deleted_on_origin_is_pruned_and_add_passes(
        self, bare_remote, monkeypatch, capsys
    ):
        """origin에서_지워진_브랜치의_옛_ref는_걷히고_add가_통과한다 — 대조군(과탐 방지)

        갱신에 `--prune`이 없으면 이 클론에 남은 옛 ref의 사본이 거짓 충돌을 낸다. 위
        테스트와 짝이다: 같은 '번호가 옛 ref에만 있다'여도 **origin에 실재하면 거부,
        origin에서 사라졌으면 통과** — 두 결과가 갈리는 것이 판정이 origin을 본다는 증거다.
        """
        _, clone = bare_remote
        other = self._seed_other_branch_with_task(clone, monkeypatch, "S9-65-other-branch-task")

        newcomer = clone("newcomer")  # other의 ref를 캐시한 채 시작한다
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0
        subprocess.run(
            ["git", "push", "--quiet", "origin", "--delete", "claude/other"],
            cwd=other,
            check=True,
            capture_output=True,
        )
        # 전제 확인: newcomer에는 옛 ref가 아직 남아 있다(갱신 전)
        assert (
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/claude/other"],
                cwd=newcomer,
                capture_output=True,
            ).returncode
            == 0
        ), "전제가 깨졌다 — 옛 ref가 없으면 prune을 재지 못한다"

        capsys.readouterr()
        assert self._add("S9-65-my-slug") == 0, "origin에 없는 브랜치의 옛 사본이 막으면 과탐이다"
        backlog, _ = store.load_backlog(newcomer)
        assert "S9-65-my-slug" in backlog.tasks

    def test_same_full_id_across_branches_is_not_a_collision(self, bare_remote, monkeypatch):
        """같은_full_ID를_다른_클론에서_재등재하는_것은_충돌이_아니다

        HARN-10 기존 규칙(슬러그가 다를 때만 충돌)을 새 출처에도 그대로 적용한다 —
        시딩·복제 세션이 같은 태스크를 다시 add하는 정상 경로를 막으면 안 된다.
        """
        _, clone = bare_remote
        self._seed_other_branch_with_task(clone, monkeypatch, "S9-70-shared-task")

        newcomer = clone("newcomer")
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0

        assert self._add("S9-70-shared-task") == 0, "같은 full ID 재등재는 통과해야 한다"

    def test_remote_task_file_scan_failure_warns_with_exception_type_but_does_not_block(
        self, bare_remote, monkeypatch, capsys
    ):
        """파일명_스캔_실패는_등재를_막지_않되_예외_타입명으로_경고한다

        CLAUDE.md 침묵 실패 금지 — scan_remote_task_files가 완전히 죽어도(모의 예외)
        add 자체는 fail-open으로 통과해야 하고, 경고에는 예외 타입명이 남아야 한다.
        """
        _, clone = bare_remote
        newcomer = clone("newcomer")
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0

        def _boom(root, **kw):
            raise RuntimeError("원격 파일명 스캔 불가")

        monkeypatch.setattr(remote_claims, "scan_remote_task_files", _boom)
        capsys.readouterr()
        assert self._add("S9-80-scan-failure-ok") == 0, "스캔 실패가 add 자체를 막으면 안 된다"
        captured = capsys.readouterr()
        assert "RuntimeError" in captured.err, "예외 타입명이 경고에 남아야 한다(침묵 실패 금지)"


class TestScanRemoteTaskFilesNetworkCostGuard:
    """`scan_remote_task_files`가 실제로 fetch 없이 캐시된 ref만 읽는지 — 단위 레벨.

    CLI 종단 테스트(위 클래스)는 "결과가 맞다"만 증명한다. 이 클래스는 acceptance
    ②(네트워크 비용 가드)를 `git fetch`가 **호출조차 되지 않는다**는 사실로 직접
    증명한다 — `scan_remote_done`이 이미 쓰는 `fetch=False` 선례와 동일한 계약.
    """

    def _spy_git(self, monkeypatch) -> list[tuple[str, ...]]:
        calls: list[tuple[str, ...]] = []
        original = remote_claims._git

        def spy(root, *argv, **kwargs):
            calls.append(argv)
            return original(root, *argv, **kwargs)

        monkeypatch.setattr(remote_claims, "_git", spy)
        return calls

    def test_default_call_never_invokes_git_fetch(self, bare_remote, monkeypatch):
        """fetch=False_기본값은_git_fetch를_호출하지_않는다"""
        _, clone = bare_remote
        newcomer = clone("newcomer")

        calls = self._spy_git(monkeypatch)
        _, status = remote_claims.scan_remote_task_files(newcomer)
        assert status == "ok"
        assert not any(
            a and a[0] == "fetch" for a in calls
        ), "fetch=False 기본값인데 git fetch가 호출됐다 — 네트워크 비용 가드 위반"

    def test_fetch_true_does_invoke_git_fetch(self, bare_remote, monkeypatch):
        """fetch=True는_명시적으로_git_fetch를_호출한다 — 위 테스트의 반대 축(변별력)"""
        _, clone = bare_remote
        newcomer = clone("newcomer")

        calls = self._spy_git(monkeypatch)
        _, status = remote_claims.scan_remote_task_files(newcomer, fetch=True)
        assert status == "ok"
        assert any(a and a[0] == "fetch" for a in calls), "fetch=True인데 git fetch가 안 불렸다"


class TestAddVisibilityNotice:
    """`add` 직후의 관측 사각 고지 — 양방향 변별력 (HARN-43).

    HARN-38(2026-08-31)의 실증된 원인은 가드의 *판정력*이 아니라 *관측 범위*였다:
    충돌 상대가 push된 적 없는 브랜치에 있어 세 출처 어디에도 나타나지 않았고,
    3출처 모두 `status=ok`였으므로 조회 실패조차 아니었다. 가드는 통과했고, 통과가
    곧 "충돌 없음"이 아니었다.

    그래서 이 고지는 **탐지가 아니라 고지**이며, 검증의 핵심은 *조용할 때 조용한가*다.
    무조건 뜨는 경고는 습관적으로 무시되어 정작 필요한 순간에 보이지 않는다 —
    즉 과탐 축(②)이 없으면 이 기능은 소음일 뿐 보호가 아니다.
    """

    def _add(self, task_id: str) -> int:
        return cli.main(
            [
                "add",
                "--eos-priority",
                "P2",
                "--id",
                task_id,
                "--title",
                "가시성 고지 변별력 테스트",
                "--track",
                "math-completion",
                "--stage",
                "S2",
            ]
        )

    def test_unpushed_branch_gets_visibility_notice(self, bare_remote, monkeypatch, capsys):
        """미push_브랜치에서는_고지가_뜬다 — 실증된 원인 축(acceptance ①)"""
        _, clone = bare_remote
        newcomer = clone("newcomer")  # claude/newcomer 로컬 생성만 — push 없음
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0

        capsys.readouterr()
        assert self._add("S9-90-unpushed") == 0, "고지는 차단이 아니다 — add는 통과해야 한다"
        err = capsys.readouterr().err

        assert "push 전까지 다른 세션에 보이지 않는다" in err
        assert "claude/newcomer" in err, "어느 브랜치가 안 보이는지 지목해야 한다"
        assert "가드 통과 ≠ 충돌 없음" in err, "고지 문안에 한계가 명시돼야 한다(acceptance ④)"

    def test_pushed_branch_gets_no_notice(self, bare_remote, monkeypatch, capsys):
        """push된_브랜치에서는_고지가_뜨지_않는다 — 과탐 축(acceptance ③의 반대쪽)

        이 축이 없으면 '항상 뜨는 문구'와 구별되지 않는다. 두 결과가 갈리는 것 자체가
        고지가 실제 관측에 근거한다는 증거다.
        """
        _, clone = bare_remote
        newcomer = clone("newcomer")
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0
        # push하면 git이 remote-tracking ref를 만든다 — "보인다"가 성립하는 유일한 경로.
        subprocess.run(
            ["git", "push", "--quiet", "-u", "origin", "claude/newcomer"],
            cwd=newcomer,
            check=True,
            capture_output=True,
        )

        capsys.readouterr()
        assert self._add("S9-91-pushed") == 0
        err = capsys.readouterr().err

        assert "push 전까지 다른 세션에 보이지 않는다" not in err
        assert "가드 통과 ≠ 충돌 없음" not in err, "조용할 때는 완전히 조용해야 한다"

    def test_stale_remote_refs_are_disclosed(self, bare_remote, monkeypatch, capsys):
        """갱신이_실패하면_마지막_전체_브랜치_fetch_경과시간을_고지한다 (acceptance ② · HARN-111 ⑦(다))

        HARN-111 이후 `add`는 스캔 직전에 원격 heads를 갱신한다(ⓓ) — 갱신이 성공하면
        스냅샷은 지금 것이라 말할 것이 없다. 고지가 필요한 것은 **갱신이 실패한** 경우이며,
        그때의 나이는 FETCH_HEAD가 아니라 **전체 브랜치 fetch 전용 스탬프**로 잰다(번호 가드의
        claim fetch가 FETCH_HEAD를 매번 새로 써서 종전 고지는 add 안에서 구조적으로 꺼져 있었다).
        claim fetch가 실제로 도는 조건(claim 브랜치 실재)을 만들어 그 무력화 경로를 태운다.
        """
        _, clone = bare_remote
        holder = clone("holder")
        assert remote_claims.claim(holder, "S2-01", "claude/holder").status == "ok"
        newcomer = clone("newcomer")
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0
        subprocess.run(
            ["git", "push", "--quiet", "-u", "origin", "claude/newcomer"],
            cwd=newcomer,
            check=True,
            capture_output=True,
        )
        # 마지막 전체 브랜치 fetch를 임계 너머 과거로 — 실제 시간 경과를 기다리지 않는다.
        _age_branch_stamp(newcomer, cli._STALE_REFS_SECONDS + 3600)
        _fail_heads_fetch(monkeypatch)

        capsys.readouterr()
        assert self._add("S9-92-stale-refs") == 0, "갱신 실패는 등재를 막지 않는다(fail-open)"
        err = capsys.readouterr().err

        # 전제(변별력): claim fetch가 실제로 FETCH_HEAD를 새로 썼다 — 종전 척도는 속았을 것이다
        fetch_head = newcomer / ".git" / "FETCH_HEAD"
        assert fetch_head.exists() and time.time() - fetch_head.stat().st_mtime < 120
        assert "원격 브랜치 목록 갱신 실패(offline" in err, "갱신 실패를 상태와 함께 말해야 한다"
        assert "원격 스냅샷이" in err and "지났다" in err and "전체 브랜치" in err
        assert "가드 통과 ≠ 충돌 없음" in err
        # push된 브랜치이므로 미push 축은 뜨면 안 된다 — 두 축이 독립임을 함께 동결한다.
        assert "push 전까지 다른 세션에 보이지 않는다" not in err

    def test_fresh_pushed_branch_notice_stays_silent_after_fetch(
        self, bare_remote, monkeypatch, capsys
    ):
        """신선한_ref는_경과시간_고지도_뜨지_않는다 — 신선도 축의 과탐 방지"""
        _, clone = bare_remote
        newcomer = clone("newcomer")
        monkeypatch.chdir(newcomer)
        assert cli.main(["seed"]) == 0
        subprocess.run(
            ["git", "push", "--quiet", "-u", "origin", "claude/newcomer"],
            cwd=newcomer,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "fetch", "--quiet", "origin"], cwd=newcomer, check=True, capture_output=True
        )

        capsys.readouterr()
        assert self._add("S9-93-fresh-refs") == 0
        assert "원격 스냅샷이" not in capsys.readouterr().err


class TestVisibilityHelpersAreNetworkFree:
    """고지 헬퍼가 실제로 fetch를 타지 않는지 — 단위 레벨 (acceptance ②의 비용 계약).

    `scan_remote_task_files`의 `test_default_call_never_invokes_git_fetch` 선례와
    같은 형태다. 고지가 네트워크를 타기 시작하면 `add`가 느려지고, 그러면 사람이
    가드를 우회할 유인이 생긴다.
    """

    def test_helpers_never_invoke_git_fetch(self, bare_remote, monkeypatch):
        """branch_has_remote_ref와_remote_refs_age_seconds는_git_fetch를_호출하지_않는다"""
        _, clone = bare_remote
        newcomer = clone("newcomer")

        calls: list[tuple[str, ...]] = []
        real_git = remote_claims._git

        def _spy(root, *argv, **kw):
            calls.append(argv)
            return real_git(root, *argv, **kw)

        monkeypatch.setattr(remote_claims, "_git", _spy)
        remote_claims.branch_has_remote_ref(newcomer, "claude/newcomer")
        remote_claims.remote_refs_age_seconds(newcomer)

        assert calls, "git을 한 번도 부르지 않았다면 이 감시 자체가 무효다"
        assert not any(
            a and a[0] == "fetch" for a in calls
        ), f"고지 헬퍼가 git fetch를 호출했다 — 네트워크 비용 가드 위반: {calls}"

    def test_unknown_branch_is_undecidable_not_false(self, bare_remote):
        """브랜치명을_모르면_None(판정_불가)이지_False가_아니다

        판정 불가를 False로 접으면 '측정 실패'가 '미push 확정'으로 위장돼 거짓 고지가
        상시화된다 — CLAUDE.md "측정 실패와 통과가 같은 색이면 안 된다"의 이 축 적용.
        """
        _, clone = bare_remote
        newcomer = clone("newcomer")
        assert remote_claims.branch_has_remote_ref(newcomer, "unknown")[0] is None
        assert remote_claims.branch_has_remote_ref(newcomer, "")[0] is None

    def test_linked_worktree_reads_shared_ref_stamps(self, bare_remote, tmp_path):
        """linked_worktree에서도_원격_ref_나이를_판정한다 (Codex P2 · PR #940)

        이 저장소는 병렬 세션에 worktree를 의무화한다(`parallel_sessions.md` "1 세션 =
        1 브랜치 = 1 worktree" · `scripts/new-session-worktree.sh`). 그런데 linked
        worktree의 `--git-dir`는 `.git/worktrees/<name>`이고 **공용 ref는 거기 없다** —
        초안은 그 디렉터리만 봐서 흔적 3종이 전부 부재, `no-ref-stamp`로 침묵했다.
        즉 **보호가 필요한 바로 그 환경에서 무력**했다.

        변별력: worktree의 `--git-dir`에 흔적이 하나도 없음을 *먼저 단언*한다. 그
        전제가 깨지면(git이 언젠가 FETCH_HEAD를 거기 만들면) 이 테스트는 공용 디렉터리를
        읽는지 여부와 무관하게 통과해 버린다 — 공허한 통과 방지.
        """
        _, clone = bare_remote
        newcomer = clone("newcomer")
        worktree = tmp_path / "linked-wt"
        subprocess.run(
            ["git", "worktree", "add", "-q", "--detach", str(worktree), "HEAD"],
            cwd=newcomer,
            check=True,
            capture_output=True,
        )

        wt_git_dir = Path(
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        if not wt_git_dir.is_absolute():
            wt_git_dir = worktree / wt_git_dir
        assert not any(
            (wt_git_dir / name).exists()
            for name in ("FETCH_HEAD", "packed-refs", "refs/remotes/origin")
        ), "worktree 전용 git-dir에 흔적이 있으면 이 테스트는 공용 조회를 검증하지 못한다"

        age, status = remote_claims.remote_refs_age_seconds(worktree)
        assert status == "ok", f"worktree에서 판정 불가가 나오면 안 된다 — status={status}"
        assert age is not None and age >= 0
