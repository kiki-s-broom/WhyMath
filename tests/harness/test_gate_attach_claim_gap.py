"""미머지 게이트 부착 스캔 — 게이트를 붙이고 claim을 푼 태스크의 착수 공백 (HARN-193).

**사고 형태** (2026-09-28 `EOS-129`이 하루에 세 세션에서 착수돼 PR 셋이 열렸다): 표준 작업 흐름이
`start` → `gates add` → `amend --gate` → `unblock`인데, `unblock`은 원격 claim을 즉시 걷고 그 자리를
대신할 트렁크 사본의 `requires_gates`는 **PR이 머지돼야** 생긴다. 그 사이 트렁크 백로그는 이 태스크를
게이트 없는 무주 todo로 보여 주고, `next`·브리핑이 1순위로 추천해 다음 세션이 연쇄 착수한다.

**픽스처는 진짜 git 원격이다** — 읽기 경로를 시임(fake)으로 검증하면 `cat-file --batch` 정렬·트렁크
해소·브랜치 ref 매핑이 전부 우회된다(HARN-11 `TestUnmergedDoneDetection`과 같은 이유).

**세 상태를 모두 밟는다** (acceptance ④ — 사고 상태만 RED이고 나머지가 GREEN임을 가르지 못하면 검사가
아니라 고장이다):
    ⓐ 게이트가 트렁크에 있음        → 정상 차단(`classify_todo`가 막는다 — 이 스캔은 발화하지 않는다)
    ⓑ 게이트가 원격 브랜치에만 있음 → **이번 사고** (start 거부 · next·brief 제외)
    ⓒ 게이트 없음                   → 착수 가능 대조군 (과잉 차단 방지)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import remote_claims
import report
import store

import backlog as cli

TASK_ID = "T193-01-gate-attach-target"
OTHER_TASK_ID = "T193-02-innocent-bystander"
GATE_ID = "G-t193-branch-only"
SECOND_GATE_ID = "G-t193-second-gate"


def _git(repo: Path, *argv: str) -> str:
    result = subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class _Scenario:
    """트렁크·게이트 부착 세션·나(신규 세션)를 실제 git으로 세우는 헬퍼."""

    def __init__(self, clone, monkeypatch):
        self.clone = clone
        self.monkeypatch = monkeypatch

    # ── 저수준 ──
    def chdir(self, repo: Path) -> None:
        self.monkeypatch.chdir(repo)

    def add_task(self, task_id: str, *extra: str) -> None:
        assert (
            cli.main(
                [
                    "add",
                    # P1 — 이월 등급(P2·P3)은 next·brief 후보에서 기본 숨김이라(HARN-77) 이 스위트의
                    # 피검체(게이트 부착 제외)에 도달하기 전에 사라진다.
                    "--eos-priority",
                    "P1",
                    "--track",
                    "math-completion",
                    "--stage",
                    "S1",
                    "--id",
                    task_id,
                    "--title",
                    f"게이트 부착 스캔 대상 {task_id}",
                    *extra,
                ]
            )
            == 0
        )

    def add_gate(self, gate_id: str) -> None:
        assert (
            cli.main(
                [
                    "gates",
                    "add",
                    gate_id,
                    "--title",
                    "대기 중 게이트",
                    "--no-inputs",
                    "테스트 픽스처 — 입력 태스크 없음",
                ]
            )
            == 0
        )

    def push_trunk(self, repo: Path) -> None:
        """현재 작업 트리 상태를 origin 트렁크(main)에 그대로 착지시킨다 (PR 머지 모사)."""
        for argv in (
            ["add", "."],
            ["commit", "-q", "-m", "trunk state (test)"],
            ["push", "--quiet", "origin", "HEAD:main"],
        ):
            _git(repo, *argv)

    def push_branch(self, repo: Path, branch: str) -> None:
        """현재 작업 트리 상태를 **트렁크가 아닌** 브랜치로 push한다 (미머지 PR 모사)."""
        for argv in (
            ["checkout", "-q", "-B", branch],
            ["add", "."],
            # 아무것도 붙이지 않은 대조 브랜치도 push할 수 있어야 한다(빈 커밋 허용)
            ["commit", "-q", "--allow-empty", "-m", "branch state (test)"],
            ["push", "--quiet", "-u", "origin", branch],
        ):
            _git(repo, *argv)

    # ── 시나리오 ──
    def landed_trunk(self, *task_ids: str) -> None:
        """트렁크에 게이트 없는 todo 태스크들이 착지한 상태."""
        lander = self.clone("lander")
        self.chdir(lander)
        assert cli.main(["seed"]) == 0
        for task_id in task_ids:
            self.add_task(task_id)
        self.push_trunk(lander)

    def attach_gate_on_branch(
        self,
        name: str,
        task_id: str = TASK_ID,
        gate_id: str = GATE_ID,
        *,
        land_on_trunk: bool = False,
        push: bool = True,
    ) -> Path:
        """이번 사고의 표준 흐름 — start → gates add → amend --gate → unblock → 브랜치 push.

        `land_on_trunk=True`면 마지막에 브랜치가 아니라 트렁크로 착지시킨다(정상 차단 상태 ⓐ).
        `push=False`면 작업만 끝내고 push는 호출자가 한다 — **두 세션이 서로를 못 본 채** 같은
        일을 하는 이력(EOS-129)을 만들려면 둘 다 끝낸 *뒤에* 각자 push해야 한다. 한쪽이 먼저
        push한 뒤에 다른 쪽이 `start`하면 이 스캔이 정확히 그 착수를 거부한다(그것이 수정의 효과다).
        """
        attacher = self.clone(name)
        self.chdir(attacher)
        assert cli.main(["start", task_id]) == 0
        self.add_gate(gate_id)
        assert cli.main(["amend", task_id, "--gate", gate_id, "--reason", "결정 선행 필요"]) == 0
        assert cli.main(["unblock", task_id]) == 0  # 원격 claim을 걷는다 — 공백이 열리는 지점
        if land_on_trunk:
            self.push_trunk(attacher)
        elif push:
            self.push_branch(attacher, f"claude/{name}")
        return attacher

    def newcomer(self, name: str = "newcomer") -> Path:
        """공백 이후에 들어온 신규 세션 — 트렁크만 본다."""
        mine = self.clone(name)
        self.chdir(mine)
        return mine


def _scenario(bare_remote, monkeypatch) -> _Scenario:
    _, clone = bare_remote
    return _Scenario(clone, monkeypatch)


# ═════════════════════════════════════════════════════════════════════════
# ⓑ 사고 상태 — 게이트가 원격 브랜치에만 있다
# ═════════════════════════════════════════════════════════════════════════
class TestAccidentState:
    def test_premise_trunk_shows_the_task_as_gate_free_todo(self, bare_remote, monkeypatch):
        """전제 고정 — 사고 상태에서 신규 세션의 로컬(=트렁크) 사본은 게이트 없는 todo다.

        이 단언이 깨지면 아래 거부 테스트들은 `classify_todo`의 게이트 거부와 구분되지 않아
        새 스캔이 아니라 기존 검사를 검증하는 공허한 테스트가 된다.
        """
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        mine = sc.newcomer()
        backlog, _ = store.load_backlog(mine)
        task = backlog.tasks[TASK_ID]
        assert task.status == "todo" and task.requires_gates == []
        assert GATE_ID not in backlog.gates
        # 그리고 원격 claim 대장은 비어 있다 — unblock이 걷었기 때문이다.
        claims, status = remote_claims.list_claims(mine)
        assert status == "ok" and [c.task_id for c in claims] == []

    def test_start_refuses_and_names_branch_and_gate(self, bare_remote, monkeypatch, capsys):
        """start가_미머지_브랜치의_게이트_부착을_거부한다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        sc.newcomer()
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 1
        err = capsys.readouterr().err
        assert "HARN-193" in err
        assert GATE_ID in err and "claude/attacher" in err
        assert "정의 없음" in err, "트렁크에 게이트 정의가 없다는 사실이 보여야 한다"
        assert "git show origin/claude/attacher:backlog/tasks/" in err, "확인 명령을 안내해야 한다"

    def test_refused_start_leaves_no_claim_behind(self, bare_remote, monkeypatch):
        """거부된 start는_원격_claim을_남기지_않는다(dangling claim 방지)"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        mine = sc.newcomer()
        assert cli.main(["start", TASK_ID]) == 1
        claims, status = remote_claims.list_claims(mine)
        assert status == "ok" and [c.task_id for c in claims] == []
        backlog, _ = store.load_backlog(mine)
        assert backlog.tasks[TASK_ID].status == "todo"

    def test_next_excludes_the_task_and_says_why(self, bare_remote, monkeypatch, capsys):
        """next가_후보에서_제외하고_이유를_말한다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        sc.newcomer()
        capsys.readouterr()
        assert cli.main(["next", "--n", "20"]) == 0
        captured = capsys.readouterr()
        assert TASK_ID not in captured.out, "게이트가 붙은 태스크가 후보로 노출되면 안 된다"
        assert "후보 제외" in captured.err and TASK_ID in captured.err
        assert GATE_ID in captured.err and "claude/attacher" in captured.err

    def test_brief_excludes_the_task_and_says_why_on_stdout(self, bare_remote, monkeypatch, capsys):
        """brief가_후보에서_제외하고_이유를_stdout에_싣는다

        훅이 stderr를 버리므로(`2>/dev/null`) 이유는 stdout에 있어야 세션이 본다.
        """
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        sc.newcomer()
        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out
        candidates = out.split("다음 착수 후보")[-1] if "다음 착수 후보" in out else ""
        assert TASK_ID not in candidates, "브리핑 후보로 노출되면 안 된다"
        assert f"후보 제외 {TASK_ID}" in out and GATE_ID in out

    def test_ignore_remote_claim_bypasses_and_leaves_an_event(
        self, bare_remote, monkeypatch, capsys
    ):
        """--ignore-remote-claim으로_우회할_수_있고_사유가_이벤트로_남는다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        mine = sc.newcomer()
        capsys.readouterr()
        assert cli.main(["start", TASK_ID, "--ignore-remote-claim"]) == 0
        assert "이중 구현" in capsys.readouterr().err
        events = "".join(
            p.read_text(encoding="utf-8") for p in (mine / "backlog").rglob("*.ndjson")
        )
        assert "start_ignored_unmerged_gate_attach" in events
        assert f"claude/attacher:{GATE_ID}" in events

    def test_a_second_would_be_attacher_is_stopped_at_start(self, bare_remote, monkeypatch, capsys):
        """연쇄_착수_차단_—_첫_세션이_push한_뒤에_들어온_둘째_세션은_start에서_막힌다

        수정 전에는 이 둘째 세션이 무마찰로 착수해 자기 게이트를 또 붙였다(EOS-129의 ⓑ).
        """
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher-a", TASK_ID, GATE_ID)
        second = sc.clone("attacher-b")
        sc.chdir(second)
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 1
        assert "claude/attacher-a" in capsys.readouterr().err

    def test_flags_only_the_task_that_carries_the_gate(self, bare_remote, monkeypatch):
        """태스크별_독립_—_게이트가_붙은_태스크만_잡고_옆_태스크는_건드리지_않는다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID, OTHER_TASK_ID)
        sc.attach_gate_on_branch("attacher", TASK_ID)
        mine = sc.newcomer()
        found, status = remote_claims.scan_remote_gate_attachments(
            mine, {TASK_ID: [], OTHER_TASK_ID: []}
        )
        assert status == "ok"
        assert set(found) == {TASK_ID}, "옆 태스크가 같이 잡히면 과잉 차단이다"
        assert [(a.gate_id, a.branch) for a in found[TASK_ID]] == [(GATE_ID, "claude/attacher")]
        assert found[TASK_ID][0].trunk_gate_state == ""  # 트렁크에 정의 없음
        assert found[TASK_ID][0].branch_gate_state == "pending"

    def test_two_branches_two_gates_are_all_reported(self, bare_remote, monkeypatch, capsys):
        """서로_다른_두_세션이_각자_게이트를_붙인_상태(EOS-129형)를_모두_보고한다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        # 둘 다 서로의 push를 못 본 채 작업을 끝낸다 → 그 뒤 각자 push (이력의 ⓐⓑ 세션 순서)
        first = sc.attach_gate_on_branch("attacher-a", TASK_ID, GATE_ID, push=False)
        second = sc.attach_gate_on_branch("attacher-b", TASK_ID, SECOND_GATE_ID, push=False)
        sc.push_branch(first, "claude/attacher-a")
        sc.push_branch(second, "claude/attacher-b")
        sc.newcomer()
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 1
        err = capsys.readouterr().err
        for needle in ("claude/attacher-a", "claude/attacher-b", GATE_ID, SECOND_GATE_ID):
            assert (
                needle in err
            ), f"{needle} 누락 — 경쟁 세션이 하나라도 가려지면 택일 판단이 틀어진다"


# ═════════════════════════════════════════════════════════════════════════
# ⓐ 정상 차단 · ⓒ 게이트 없음 — 대조군 (과잉 차단 방지)
# ═════════════════════════════════════════════════════════════════════════
class TestControls:
    def test_gate_already_on_trunk_is_handled_by_the_ordinary_check(
        self, bare_remote, monkeypatch, capsys
    ):
        """ⓐ_게이트가_트렁크에_있으면_기존_검사가_막고_이_스캔은_발화하지_않는다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher", land_on_trunk=True)
        mine = sc.newcomer()
        found, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: [GATE_ID]})
        assert (found, status) == ({}, "ok"), "로컬이 이미 아는 게이트는 중복 판정하지 않는다"
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 1  # classify_todo의 게이트 거부
        err = capsys.readouterr().err
        assert (
            "HARN-193" not in err
        ), "트렁크에 있는 게이트를 이 스캔이 자기 것처럼 보고하면 안 된다"
        assert GATE_ID in err

    def test_no_gate_anywhere_allows_start_and_lists_the_task(
        self, bare_remote, monkeypatch, capsys
    ):
        """ⓒ_게이트가_어디에도_없으면_착수되고_후보에_보인다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        # 다른 브랜치가 존재하지만 이 태스크에 아무것도 붙이지 않았다 — 브랜치 존재만으로 막으면 고장이다.
        bystander = sc.clone("bystander")
        sc.chdir(bystander)
        sc.push_branch(bystander, "claude/bystander")
        sc.newcomer()
        capsys.readouterr()
        assert cli.main(["next", "--n", "20"]) == 0
        assert TASK_ID in capsys.readouterr().out
        assert cli.main(["start", TASK_ID]) == 0

    def test_merged_but_undeleted_branch_is_not_reported(self, bare_remote, monkeypatch):
        """PR은_머지됐지만_브랜치가_안_지워진_상태_—_트렁크가_이미_아는_부착은_'미머지'가_아니다

        가장 흔한 실전 상태다(머지된 PR 브랜치는 한동안 남는다). 호출자의 로컬 맵을 **비워서**
        트렁크 쪽 차집합만 홀로 시험한다 — 로컬 맵이 가려 주면 이 축은 검증되지 않는다.
        """
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        attacher = sc.attach_gate_on_branch("attacher")  # 브랜치 push (게이트 부착본)
        _git(attacher, "push", "--quiet", "origin", "HEAD:main")  # 그 PR이 머지됨 — 브랜치는 잔존
        mine = sc.newcomer()
        found, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []})
        assert (found, status) == ({}, "ok"), "머지된 부착을 미머지로 보고하면 영구 오차단이다"

    def test_locally_known_gate_is_not_reported_again(self, bare_remote, monkeypatch):
        """호출자_로컬이_이미_아는_게이트는_중복_보고하지_않는다(classify_todo의_몫)

        트렁크는 모르고(브랜치에만 있음) 로컬은 아는 상태로 로컬 쪽 차집합만 홀로 시험한다.
        """
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        mine = sc.newcomer()
        unknown, _ = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []})
        known, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: [GATE_ID]})
        assert set(unknown) == {TASK_ID}, "대조 — 로컬이 모르면 잡혀야 이 테스트가 공허하지 않다"
        assert (known, status) == ({}, "ok")

    def test_gate_cleared_on_trunk_is_not_a_blocker(self, bare_remote, monkeypatch):
        """과잉_차단_대조군_—_트렁크가_이미_통과시킨_게이트를_낡은_브랜치가_들고_있어도_무시한다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        attacher = sc.attach_gate_on_branch("attacher")
        # 트렁크에서 그 게이트가 나중에 정의되고 통과된 상태를 만든다(다른 세션이 결정을 내림).
        decider = sc.clone("decider")
        sc.chdir(decider)
        sc.add_gate(GATE_ID)
        assert (
            cli.main(
                [
                    "gates",
                    "clear",
                    GATE_ID,
                    "--as",
                    "kiki",
                    "--evidence",
                    "테스트",
                    "--no-base",
                    "픽스처",
                ]
            )
            == 0
        )
        sc.push_trunk(decider)
        assert attacher.exists()
        mine = sc.newcomer()
        found, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []})
        assert (found, status) == ({}, "ok")

    def test_own_branch_is_excluded(self, bare_remote, monkeypatch):
        """세션_자신의_브랜치는_제외한다_—_내_로컬_사본이_내가_push한_사본보다_최신이다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        attacher = sc.attach_gate_on_branch("attacher")
        with_self, _ = remote_claims.scan_remote_gate_attachments(attacher, {TASK_ID: []})
        without_self, status = remote_claims.scan_remote_gate_attachments(
            attacher, {TASK_ID: []}, exclude_branches=["claude/attacher"]
        )
        assert set(with_self) == {
            TASK_ID
        }, "제외 인자가 없으면 자기 브랜치도 잡혀야 대조가 성립한다"
        assert (without_self, status) == ({}, "ok")

    def test_trunk_ref_itself_is_never_a_finding(self, bare_remote, monkeypatch):
        """트렁크_ref는_후보가_아니다_—_트렁크가_들고_있는_게이트는_'미머지'가_아니다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher", land_on_trunk=True)
        mine = sc.newcomer()
        found, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []})
        assert (found, status) == ({}, "ok")


# ═════════════════════════════════════════════════════════════════════════
# 표시 정직성 (acceptance ⑤) — 측정 실패가 '부착 없음'으로 위장되지 않는다
# ═════════════════════════════════════════════════════════════════════════
class TestScanStatusHonesty:
    def test_start_says_unknown_when_the_gate_scan_fails_and_still_proceeds(
        self, bare_remote, monkeypatch, capsys
    ):
        """스캔_실패는_경고와_예외_타입명을_남기고_진행한다(fail-open)"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.newcomer()
        monkeypatch.setattr(
            remote_claims,
            "scan_remote_gate_attachments",
            lambda *a, **k: ({}, "error:RuntimeError"),
        )
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 0, "탐지 실패가 착수 자체를 막으면 안 된다"
        err = capsys.readouterr().err
        assert "미머지 게이트 부착 탐지 불가" in err and "error:RuntimeError" in err

    def test_start_reports_gate_scan_unknown_when_the_fetch_itself_failed(
        self, bare_remote, monkeypatch, capsys
    ):
        """fetch가_실패해_done_스캔이_불가면_게이트_부착도_판정_불가라고_따로_말한다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.newcomer()
        monkeypatch.setattr(remote_claims, "scan_remote_done", lambda *a, **k: ({}, "offline"))
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 0
        err = capsys.readouterr().err
        assert "미머지 done 탐지 불가(offline)" in err
        assert "미머지 게이트 부착 탐지 불가(offline)" in err, "묻어 가지 않고 따로 보여야 한다"

    def test_next_says_unknown_when_the_gate_scan_fails(self, bare_remote, monkeypatch, capsys):
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.newcomer()
        monkeypatch.setattr(
            remote_claims, "scan_remote_gate_attachments", lambda *a, **k: ({}, "offline")
        )
        capsys.readouterr()
        assert cli.main(["next", "--n", "20"]) == 0
        captured = capsys.readouterr()
        assert TASK_ID in captured.out, "판정 불가가 후보를 지우면 안 된다(fail-open)"
        assert "미머지 게이트 부착 탐지 불가(offline)" in captured.err

    def test_brief_survives_scan_exception_and_prints_the_failure_on_stdout(
        self, bare_remote, monkeypatch, capsys
    ):
        """brief는_스캔_예외에도_막히지_않고_실패를_stdout에_보인다(훅은_stderr를_버린다)"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.newcomer()

        def _boom(*a, **k):
            raise RuntimeError("원격 불가")

        monkeypatch.setattr(remote_claims, "scan_remote_gate_attachments", _boom)
        capsys.readouterr()
        assert cli.main(["brief"]) == 0, "필터 실패가 브리핑 자체를 막으면 안 된다(fail-open)"
        out = capsys.readouterr().out
        assert "[빌드하네스 브리핑]" in out
        assert "error:RuntimeError" in out and "판정 보류" in out

    def test_render_brief_default_output_is_unchanged_for_old_callers(
        self, bare_remote, monkeypatch
    ):
        """하위호환_—_새_인자를_안_주는_기존_호출부의_출력에는_새_줄이_없다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        mine = sc.newcomer()
        backlog, errors = store.load_backlog(mine)
        from datetime import date

        text = report.render_brief(backlog, errors, "claude/x", date(2026, 9, 30))
        assert "게이트를 붙여 뒀다" not in text and "미머지 게이트 부착 스캔" not in text

    def test_batch_misalignment_is_unknown_not_a_silent_zip(self, bare_remote, monkeypatch):
        """cat-file_출력_정렬이_어긋나면_엉뚱한_브랜치에_붙이지_않고_판정_불가로_돌린다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        mine = sc.newcomer()
        real = remote_claims._iter_batch_blobs

        def _dropping(stdout):
            items = list(real(stdout))
            yield from items[:-1]  # 한 건을 흘린다

        monkeypatch.setattr(remote_claims, "_iter_batch_blobs", _dropping)
        found, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []})
        assert found == {} and status == "error:BatchMisaligned"

    def test_branch_cap_reports_truncated_but_keeps_what_it_found(self, bare_remote, monkeypatch):
        """브랜치_상한을_넘으면_truncated_—_발견분은_유지하고_'전부_봤다'고_말하지_않는다"""
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        mine = sc.newcomer()
        _, full_status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []})
        assert full_status == "ok"
        found, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []}, max_refs=1)
        assert status == "truncated"
        assert set(found) <= {TASK_ID}

    def test_no_origin_is_offline(self, git_repo):
        found, status = remote_claims.scan_remote_gate_attachments(git_repo, {TASK_ID: []})
        assert (found, status) == ({}, "offline")

    def test_empty_task_map_is_ok_without_touching_git(self, tmp_path):
        assert remote_claims.scan_remote_gate_attachments(tmp_path, {}) == ({}, "ok")


# ═════════════════════════════════════════════════════════════════════════
# shallow·단일 브랜치 클론 (acceptance ⑤) — '0개를 훑었다'는 '없다'가 아니다
# ═════════════════════════════════════════════════════════════════════════
class TestShallowSingleBranchClone:
    """`--depth 1` 클론은 트렁크 ref만 캐시한다(2026-09-30 실측: 캐시가 HEAD·main뿐).

    그 상태에서 `fetch=False` 스캔이 다른 브랜치를 0개 훑고도 `ok`를 돌려주면 측정 실패가
    '게이트 부착 없음'으로 위장된다 — 정확히 이 스캔이 막으려는 공백이 스캔 자신 안에 생긴다.
    한편 블롭 읽기는 히스토리에 의존하지 않으므로(`scan_stale_branches`의 ahead 계산과 다르다)
    fetch로 ref만 채우면 shallow 클론에서도 정확히 동작해야 한다 — 이 주장도 실측한다.
    """

    def _accident_then_shallow(self, sc: _Scenario, shallow_clone) -> Path:
        sc.landed_trunk(TASK_ID)
        sc.attach_gate_on_branch("attacher")
        mine = shallow_clone("shallow-session")  # 픽스처가 shallow 여부를 스스로 assert한다
        sc.chdir(mine)
        cached = _git(mine, "for-each-ref", "--format=%(refname)", "refs/remotes/origin")
        assert (
            "claude/attacher" not in cached
        ), "전제 — 단일 브랜치 클론은 다른 브랜치를 캐시하지 않는다"
        return mine

    def test_cached_refs_without_other_branches_is_unknown_not_ok(
        self, bare_remote, monkeypatch, shallow_clone
    ):
        """캐시에_다른_브랜치가_없으면_ok가_아니라_no_refs다"""
        sc = _scenario(bare_remote, monkeypatch)
        mine = self._accident_then_shallow(sc, shallow_clone)
        found, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []})
        assert (found, status) == ({}, "no_refs")

    def test_fetching_refs_makes_the_scan_work_in_a_shallow_clone(
        self, bare_remote, monkeypatch, shallow_clone
    ):
        """fetch로_ref를_채우면_shallow_클론에서도_사고_상태를_정확히_잡는다"""
        sc = _scenario(bare_remote, monkeypatch)
        mine = self._accident_then_shallow(sc, shallow_clone)
        found, status = remote_claims.scan_remote_gate_attachments(mine, {TASK_ID: []}, fetch=True)
        assert status == "ok"
        assert [(a.gate_id, a.branch) for a in found[TASK_ID]] == [(GATE_ID, "claude/attacher")]

    def test_start_in_a_shallow_clone_still_refuses(
        self, bare_remote, monkeypatch, shallow_clone, capsys
    ):
        """start는_fetch로_확정하므로_shallow_클론에서도_거부한다"""
        sc = _scenario(bare_remote, monkeypatch)
        self._accident_then_shallow(sc, shallow_clone)
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 1
        assert "HARN-193" in capsys.readouterr().err

    def test_next_says_unknown_in_a_shallow_clone_and_keeps_the_candidate(
        self, bare_remote, monkeypatch, shallow_clone, capsys
    ):
        """next는_fetch를_안_하므로_shallow_클론에서_판정_불가를_말하고_후보를_지우지_않는다"""
        sc = _scenario(bare_remote, monkeypatch)
        self._accident_then_shallow(sc, shallow_clone)
        capsys.readouterr()
        assert cli.main(["next", "--n", "20"]) == 0
        captured = capsys.readouterr()
        assert "미머지 게이트 부착 탐지 불가(no_refs)" in captured.err
        assert TASK_ID in captured.out, "판정 불가가 후보를 지우면 안 된다(fail-open)"

    def test_brief_in_a_shallow_clone_catches_the_accident_via_its_own_fetch(
        self, bare_remote, monkeypatch, shallow_clone, capsys
    ):
        """brief는_문서_시리즈_스캔이_먼저_fetch하므로_shallow_클론에서도_사고를_잡는다

        실측(2026-09-30): `next` 뒤 캐시는 그대로지만 `brief` 뒤에는 다른 브랜치 ref가 생긴다.
        fetch를 수행하는 것은 `brief` 안에서 먼저 도는 `scan_doc_series_duplicates`(기본
        `fetch=True`)다 — 그 스캔을 끄는 대조 실험으로 확인했다(stale-branch 스캔은 shallow
        클론에서 fetch 앞에서 물러나므로 원인이 아니다). 이 순서는 우연한 부산물이라
        **고정된 계약이 아니다** — 바로 아래 테스트가 그 스캔이 빠진 상태를 잠근다.
        """
        sc = _scenario(bare_remote, monkeypatch)
        self._accident_then_shallow(sc, shallow_clone)
        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out
        candidates = out.split("다음 착수 후보")[-1] if "다음 착수 후보" in out else ""
        assert TASK_ID not in candidates
        assert f"후보 제외 {TASK_ID}" in out

    def test_brief_falls_back_to_no_refs_when_nothing_else_fetched(
        self, bare_remote, monkeypatch, shallow_clone, capsys
    ):
        """문서_시리즈_스캔이_fetch하지_않으면_brief는_no_refs로_정직하게_물러난다(fail-open)"""

        class _NoDocSeries:
            status = "ok"
            candidates: list = []

        monkeypatch.setattr(
            remote_claims, "scan_doc_series_duplicates", lambda *a, **k: _NoDocSeries()
        )
        sc = _scenario(bare_remote, monkeypatch)
        self._accident_then_shallow(sc, shallow_clone)
        capsys.readouterr()
        assert cli.main(["brief"]) == 0
        out = capsys.readouterr().out
        assert "게이트 부착 스캔 no_refs" in out and "판정 보류" in out
        assert TASK_ID in out.split("다음 착수 후보")[-1], "판정 불가가 후보를 지우면 안 된다"

    def test_render_brief_shows_no_refs_as_unknown(self, bare_remote, monkeypatch):
        """render는_no_refs를_'부착_없음'이_아니라_'판정_보류'로_그린다(훅은_stderr를_버린다)"""
        from datetime import date

        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        mine = sc.newcomer()
        backlog, errors = store.load_backlog(mine)
        text = report.render_brief(
            backlog, errors, "claude/x", date(2026, 9, 30), gate_attach_status="no_refs"
        )
        assert "게이트 부착 스캔 no_refs" in text and "판정 보류" in text

    def test_start_does_not_cry_wolf_when_the_repo_really_has_no_other_branch(
        self, bare_remote, monkeypatch, capsys
    ):
        """과잉_경고_대조군_—_직전에_fetch했다면_브랜치_0개는_'없다'이지_'못_봤다'가_아니다

        **픽스처가 그 절을 밟아야 한다** — 트렁크 착지 과정의 `add`가 번호 예약용
        `harness-claims` 브랜치를 원격에 만들어, 그대로 두면 '다른 브랜치가 있는' 상태라
        `no_refs` 절에 닿지 않는다(첫 뮤테이션 실행에서 M27·M28이 생존한 원인). 그래서
        부산물 브랜치를 지워 **정말 main뿐인** 원격을 만들고, 그 사실을 스스로 단언한다.
        """
        bare, _ = bare_remote
        sc = _scenario(bare_remote, monkeypatch)
        sc.landed_trunk(TASK_ID)
        for head in _git(bare, "for-each-ref", "--format=%(refname:short)", "refs/heads").split():
            if head != "main":
                _git(bare, "update-ref", "-d", f"refs/heads/{head}")
        remaining = _git(bare, "for-each-ref", "--format=%(refname:short)", "refs/heads")
        assert remaining.split() == [
            "main"
        ], "전제 — 원격에 main만 남아야 이 대조군이 공허하지 않다"
        sc.newcomer()
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 0
        assert "미머지 게이트 부착 탐지 불가" not in capsys.readouterr().err
