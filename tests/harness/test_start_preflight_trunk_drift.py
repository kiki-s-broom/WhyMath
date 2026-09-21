"""start 프리플라이트 — 트렁크 의존·게이트 시차 탐지 (HARN-91).

`start`의 착수 자격 판정(`selector.classify_todo`)은 **로컬 작업 트리의 백로그 사본**만
읽는다. 내 클론이 마지막으로 fetch한 뒤 origin/main에 새로 착지한 의존·게이트(조건이
*강화*되는 방향)는 그 판정에 반영되지 않는다 — 2026-09-08 실증: `HARN-87`이 로컬 기준
의존 0건으로 통과했으나 origin/main은 이미 그 태스크에 신규 depends_on을 담고 있었다.

`scan_trunk_task_drift`(remote_claims.py)가 트렁크 사본의 태스크 파일을 직접 읽어 그
시차를 좁힌다. 여기서는 real git remote(`bare_remote`)로 실제 시차 상태를 만들어
검출을 확인한다(acceptance ④의 변별력 요구 — 정상 상태에서 초록인 것은 보호의 증거가
아니다):
    ⓐ 로컬은 의존 0건·트렁크는 의존 1건(미충족) → 거부
    ⓑ 로컬은 게이트 미부착·트렁크는 pending 게이트 부착 → 거부
    ⓒ 대조군 — 로컬과 트렁크가 같으면 추가 거부가 일어나지 않는다
    ⓓ 원격 조회 실패는 '이상 없음'이 아니라 조회 실패 사실이 보여야 한다(무증상 금지)

시간 순서에 주의: 각 테스트는 **로컬 세션(mine)을 먼저 클론·시딩한 뒤** 별도 세션
(lander)이 트렁크(main)에 새 상태를 push한다 — 실제 시나리오(내가 작업을 시작한 뒤
다른 PR이 먼저 main에 머지됨)와 같은 순서다. 거꾸로 하면 `mine`의 클론이 이미
`lander`가 push한 backlog/를 받아 온 상태로 시작해 `seed`가 "이미 존재"로 거부된다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import remote_claims

import backlog as cli


class TestTrunkDependencyGateDrift:
    """HARN-91 — start의 착수 자격 판정에 트렁크 시차를 반영하는 프리플라이트."""

    TASK_ID = "T91-01-drift-target"
    DEP_ID = "T91-02-dep-unmet"
    GATE_ID = "G-t91-pending"

    def _chdir_seed(self, repo: Path, monkeypatch) -> None:
        monkeypatch.chdir(repo)
        assert cli.main(["seed"]) == 0

    def _add(self, *extra_args: str) -> None:
        assert (
            cli.main(
                [
                    "add",
                    "--eos-priority",
                    "P2",
                    "--track",
                    "math-completion",
                    "--stage",
                    "S1",
                    *extra_args,
                ]
            )
            == 0
        )

    def _push_to_trunk(self, repo: Path) -> None:
        """이 작업 트리의 현재 상태를 origin의 트렁크(main)에 그대로 착지시킨다.

        실제 시나리오(다른 세션의 PR이 먼저 main에 머지됨)를 모사 — 브랜치명과 무관하게
        `HEAD:main`으로 push해 로컬 브랜치명이 무엇이든 트렁크에 반영되게 한다.
        """
        for argv in (
            ["add", "."],
            ["commit", "-q", "-m", "trunk state (test)"],
            ["push", "--quiet", "origin", "HEAD:main"],
        ):
            subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)

    def test_start_rejects_unmet_trunk_dependency(self, bare_remote, monkeypatch, capsys):
        """①_트렁크에만_있는_미충족_의존을_start가_거부한다"""
        _, clone = bare_remote

        # 로컬 세션 — 신규 의존이 트렁크에 착지하기 *전*에 같은 태스크를 등재해 둔다.
        mine = clone("newcomer")
        self._chdir_seed(mine, monkeypatch)
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크")

        # 트렁크(main) — 다른 세션이 이 태스크에 신규 의존을 부착해 먼저 머지한다.
        lander = clone("lander")
        self._chdir_seed(lander, monkeypatch)
        self._add("--id", self.DEP_ID, "--title", "트렁크 전용 의존 — 아직 미완료")
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크", "--depends", self.DEP_ID)
        self._push_to_trunk(lander)

        monkeypatch.chdir(mine)
        assert cli.main(["start", self.TASK_ID]) == 1
        captured = capsys.readouterr()
        assert "HARN-91" in captured.err
        assert self.DEP_ID in captured.err
        assert "의존 미충족" in captured.err

    def test_start_rejects_pending_trunk_gate(self, bare_remote, monkeypatch, capsys):
        """②_트렁크에만_있는_pending_게이트를_start가_거부한다"""
        _, clone = bare_remote

        mine = clone("newcomer-gate")
        self._chdir_seed(mine, monkeypatch)
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크")

        lander = clone("lander-gate")
        self._chdir_seed(lander, monkeypatch)
        assert cli.main(["gates", "add", self.GATE_ID, "--title", "대기 중 게이트"]) == 0
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크", "--gates", self.GATE_ID)
        self._push_to_trunk(lander)

        monkeypatch.chdir(mine)
        assert cli.main(["start", self.TASK_ID]) == 1
        captured = capsys.readouterr()
        assert "HARN-91" in captured.err
        assert self.GATE_ID in captured.err
        assert "게이트 미통과" in captured.err

    def test_start_allows_when_trunk_matches_local(self, bare_remote, monkeypatch, capsys):
        """③_대조군_—_로컬과_트렁크가_같은_의존이면_추가_거부가_없다"""
        _, clone = bare_remote

        # 로컬도 같은 의존을 이미 알고 있고(=classify_todo 대상), 그 의존을 완료해 둔다 —
        # 트렁크가 그 의존의 상태를 어떻게 보든(drift 검사는 로컬에 이미 있는 항목은
        # 건너뛴다) 이 축의 관심사가 아니다.
        mine = clone("newcomer-match")
        self._chdir_seed(mine, monkeypatch)
        self._add("--id", self.DEP_ID, "--title", "공통 의존")
        assert cli.main(["start", self.DEP_ID]) == 0
        assert cli.main(["done", self.DEP_ID, "--artifact", "abc123 (#1)"]) == 0
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크", "--depends", self.DEP_ID)

        lander = clone("lander-match")
        self._chdir_seed(lander, monkeypatch)
        self._add("--id", self.DEP_ID, "--title", "공통 의존")
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크", "--depends", self.DEP_ID)
        self._push_to_trunk(lander)

        monkeypatch.chdir(mine)
        assert cli.main(["start", self.TASK_ID]) == 0

    def test_start_warns_but_proceeds_when_trunk_drift_scan_fails(
        self, bare_remote, monkeypatch, capsys
    ):
        """④_트렁크_시차_탐지_실패는_무증상이_아니라_경고와_함께_진행한다(fail-open)"""
        _, clone = bare_remote

        mine = clone("newcomer-scanfail")
        self._chdir_seed(mine, monkeypatch)
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크")

        def _boom(root, task):
            return remote_claims.TrunkDriftResult("error:RuntimeError")

        monkeypatch.setattr(remote_claims, "scan_trunk_task_drift", _boom)
        assert cli.main(["start", self.TASK_ID]) == 0, "탐지 실패가 착수 자체를 막으면 안 된다"
        captured = capsys.readouterr()
        assert "트렁크 의존·게이트 시차 탐지 불가" in captured.err
        assert "error:RuntimeError" in captured.err, "예외 타입명을 남겨야 한다(무타입 경고 금지)"

    def test_ignore_remote_claim_bypasses_trunk_drift(self, bare_remote, monkeypatch, capsys):
        """⑤_--ignore-remote-claim으로_트렁크_시차_거부를_우회할_수_있다"""
        _, clone = bare_remote

        mine = clone("newcomer-bypass")
        self._chdir_seed(mine, monkeypatch)
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크")

        lander = clone("lander-bypass")
        self._chdir_seed(lander, monkeypatch)
        self._add("--id", self.DEP_ID, "--title", "트렁크 전용 의존")
        self._add("--id", self.TASK_ID, "--title", "드리프트 대상 태스크", "--depends", self.DEP_ID)
        self._push_to_trunk(lander)

        monkeypatch.chdir(mine)
        assert cli.main(["start", self.TASK_ID, "--ignore-remote-claim"]) == 0
        assert "시차 무시하고 진행" in capsys.readouterr().err
