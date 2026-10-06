"""next·start의 낡은 로컬 대장 고지 (HARN-54).

문제: 내 클론의 백로그가 낡으면 origin/main에서는 이미 done인 태스크가 로컬에선 todo라
`next`가 후보로 내놓고 `start`가 그대로 착수시킨다. 기존 스캔은 이 창을 못 본다 —
`scan_remote_done`은 트렁크 ref를 *일부러 제외*하고, `scan_trunk_task_drift`는 의존·게이트의
강화만 본다. 실측(2026-09-24): `EOS-69` 중복 구현 사고 — start의 경고는 path_overlap 4줄에
묻혔다.

검증하는 것(acceptance ④ — 정상 상태에서 초록인 것은 보호의 증거가 아니다):
    ⓐ 트렁크 done  → next·start에 고지가 뜬다 (양성)
    ⓑ 트렁크 todo  → 고지가 뜨지 않는다 (대조군 — 무조건 뜨는 고지는 습관화된다)
    ⓒ 트렁크 cancelled도 종결로 센다
    ⓓ 차단이 아니다 — start는 exit 0, next는 후보를 그대로 둔다 (acceptance ②)
    ⓔ 조회 불가는 침묵하지 않고 '대조 불가'로 말한다 (측정 실패 ≠ 통과)
    ⓕ 스냅샷이 낡았으면 그 사실을 고지하고, 신선하면 조용하다 (acceptance ③)
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import number_guard
import remote_claims

import backlog as cli

TASK_ID = "T54-01-stale-ledger-target"
NOTICE = "낡은 로컬 대장"
UNREADABLE = "트렁크 종결 대조 불가"


def _git(repo: Path, *argv: str) -> str:
    out = subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _add(task_id: str = TASK_ID) -> None:
    # P1 — P2·P3는 next에서 기본 숨김이라(HARN-77) 후보에 오르지 않는다
    assert (
        cli.main(
            [
                "add",
                "--id",
                task_id,
                "--title",
                "낡은 대장 대상 태스크",
                "--eos-priority",
                "P1",
                "--track",
                "math-completion",
                "--stage",
                "S1",
            ]
        )
        == 0
    )


def _push_to_trunk(repo: Path) -> None:
    for argv in (
        ["add", "."],
        ["commit", "-q", "-m", "trunk state (test)"],
        ["push", "--quiet", "origin", "HEAD:main"],
    ):
        subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)


def _land_on_trunk(clone, monkeypatch, name: str, outcome: str) -> None:
    """다른 세션이 이 태스크를 `outcome`(done|cancelled|todo) 상태로 main에 착지시킨다."""
    lander = clone(name)
    monkeypatch.chdir(lander)
    assert cli.main(["seed"]) == 0
    _add()
    if outcome == "done":
        assert cli.main(["start", TASK_ID]) == 0
        assert cli.main(["done", TASK_ID, "--artifact", "abc123 (#1)"]) == 0
    elif outcome == "cancelled":
        assert cli.main(["cancel", TASK_ID, "--reason", "테스트 — 중복 태스크"]) == 0
    else:
        assert outcome == "todo"
    _push_to_trunk(lander)


def _stale_session(clone, monkeypatch, name: str) -> Path:
    """로컬 대장은 이 태스크를 todo로 아는 낡은 세션. 트렁크 착지 *전에* 만들어 둔다."""
    mine = clone(name)
    monkeypatch.chdir(mine)
    assert cli.main(["seed"]) == 0
    _add()
    return mine


def _refresh_refs(mine: Path) -> None:
    """내 클론의 remote-tracking ref를 갱신한다 — `next`는 fetch하지 않으므로(네트워크 0)
    사용자가 한 번이라도 fetch했다는 가정을 재현한다."""
    _git(mine, "fetch", "--quiet", "origin")


class TestNextNotice:
    """ⓐⓑⓒⓓ — `next`는 후보를 그대로 두고 stderr로 고지한다."""

    def test_next_notices_task_already_done_on_trunk(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-a")
        _land_on_trunk(clone, monkeypatch, "lander-a", "done")
        _refresh_refs(mine)

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50"]) == 0
        captured = capsys.readouterr()
        assert NOTICE in captured.err
        assert TASK_ID in captured.err
        assert "done" in captured.err
        # 차단·제외가 아니다 — 후보 목록에는 그대로 있다 (acceptance ②)
        assert TASK_ID in captured.out

    def test_next_is_quiet_when_trunk_still_todo(self, bare_remote, monkeypatch, capsys):
        """ⓑ 대조군 — 트렁크도 todo면 고지가 없다. 무조건 뜨는 고지는 소음이다."""
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-b")
        _land_on_trunk(clone, monkeypatch, "lander-b", "todo")
        _refresh_refs(mine)

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50"]) == 0
        captured = capsys.readouterr()
        assert NOTICE not in captured.err
        assert UNREADABLE not in captured.err
        assert TASK_ID in captured.out

    def test_next_counts_cancelled_as_terminal(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-c")
        _land_on_trunk(clone, monkeypatch, "lander-c", "cancelled")
        _refresh_refs(mine)

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50"]) == 0
        captured = capsys.readouterr()
        assert NOTICE in captured.err
        assert "cancelled" in captured.err

    def test_next_json_keeps_stdout_machine_readable(self, bare_remote, monkeypatch, capsys):
        """고지는 stderr다 — --json의 stdout은 기계가 읽으므로 오염하면 안 된다."""
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-j")
        _land_on_trunk(clone, monkeypatch, "lander-j", "done")
        _refresh_refs(mine)

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50", "--json"]) == 0
        captured = capsys.readouterr()
        assert NOTICE in captured.err
        assert NOTICE not in captured.out
        assert TASK_ID in {row["id"] for row in json.loads(captured.out)}

    def test_next_reports_unreadable_trunk_instead_of_going_silent(
        self, bare_remote, monkeypatch, capsys
    ):
        """ⓔ 조회 불가를 '끝난 것 없음'과 같은 색으로 두지 않는다."""
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-e")
        monkeypatch.setattr(
            remote_claims,
            "scan_trunk_terminal",
            lambda *a, **k: remote_claims.TrunkTerminalResult("error:OSError"),
        )

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50"]) == 0
        captured = capsys.readouterr()
        assert UNREADABLE in captured.err
        assert "error:OSError" in captured.err

    def test_next_no_remote_skips_the_comparison(self, bare_remote, monkeypatch, capsys):
        """--no-remote는 원격 조회 전체를 끈다는 기존 계약 — 이 고지도 따라 꺼진다."""
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-n")
        _land_on_trunk(clone, monkeypatch, "lander-n", "done")
        _refresh_refs(mine)

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50", "--no-remote"]) == 0
        assert NOTICE not in capsys.readouterr().err


class TestSnapshotAge:
    """ⓕ 스냅샷이 낡았으면 말한다 — `main에 없음`과 `main을 최근에 못 봤음`은 다른 진술이다."""

    def _write_stamp(self, mine: Path, age: timedelta) -> None:
        common = Path(_git(mine, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        ts = (datetime.now(timezone.utc) - age).strftime("%Y-%m-%dT%H:%M:%SZ")
        (common / number_guard.STAMP_FILE).write_text(json.dumps({"ts": ts}), encoding="utf-8")

    def test_old_snapshot_is_disclosed(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-old")
        self._write_stamp(mine, timedelta(hours=3))

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50"]) == 0
        err = capsys.readouterr().err
        assert "스냅샷" in err
        assert "3시간" in err

    def test_fresh_snapshot_is_quiet(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-fresh")
        self._write_stamp(mine, timedelta(minutes=2))

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50"]) == 0
        assert "스냅샷" not in capsys.readouterr().err

    def test_unknown_age_is_silent(self, bare_remote, monkeypatch, capsys):
        """스탬프가 없으면 판정 불가 — 추측을 출력하지 않는다."""
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-nostamp")
        # `add`가 방금 스탬프를 썼다 — 지워야 '판정 불가' 경로를 실제로 밟는다
        stamp = Path(_git(mine, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        (stamp / number_guard.STAMP_FILE).unlink()

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["next", "--n", "50"]) == 0
        assert "스냅샷" not in capsys.readouterr().err


class TestStartNotice:
    """`start`는 차단하지 않고, 겹침 경고에 묻히지 않도록 마지막에 고지한다."""

    def test_start_notices_task_done_on_trunk_but_proceeds(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-s1")
        _land_on_trunk(clone, monkeypatch, "lander-s1", "done")

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 0  # 차단이 아니다 (acceptance ②)
        captured = capsys.readouterr()
        assert "이미 **done**" in captured.err
        assert "git merge --ff-only" in captured.err
        # 고지가 stderr의 *마지막* 덩어리다 — 앞선 경고에 묻히지 않는다
        assert captured.err.rstrip().endswith("!" * 64)

    def test_start_is_quiet_when_trunk_still_todo(self, bare_remote, monkeypatch, capsys):
        """ⓑ 대조군 — 트렁크도 todo면 고지가 없다."""
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-s2")
        _land_on_trunk(clone, monkeypatch, "lander-s2", "todo")

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 0
        err = capsys.readouterr().err
        assert "이미 **" not in err
        assert UNREADABLE not in err

    def test_start_notices_cancelled_on_trunk(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-s3")
        _land_on_trunk(clone, monkeypatch, "lander-s3", "cancelled")

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 0
        assert "이미 **cancelled**" in capsys.readouterr().err

    def test_start_records_an_event_for_the_notice(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-s4")
        _land_on_trunk(clone, monkeypatch, "lander-s4", "done")

        monkeypatch.chdir(mine)
        assert cli.main(["start", TASK_ID]) == 0
        shards = sorted((mine / "backlog" / "events").glob("*"))
        assert shards, "이벤트 샤드가 생기지 않았다"
        events = "".join(f.read_text(encoding="utf-8") for f in shards)
        assert "start_trunk_terminal_notice" in events

    def test_start_reports_unreadable_trunk(self, bare_remote, monkeypatch, capsys):
        """ⓔ 대조 실패는 침묵이 아니라 '대조 불가'로 보인다."""
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-s5")
        monkeypatch.setattr(
            remote_claims,
            "scan_trunk_terminal",
            lambda *a, **k: remote_claims.TrunkTerminalResult("error:OSError"),
        )

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 0
        err = capsys.readouterr().err
        assert UNREADABLE in err
        assert "error:OSError" in err

    def test_start_says_so_when_the_fetch_itself_failed(self, bare_remote, monkeypatch, capsys):
        """ⓔ fetch가 실패하면 ref가 최신화되지 않았다 — 그 사유 그대로 '대조 불가'라고 말한다.
        (실패를 ok로 접으면 낡은 ref로 '끝난 것 없음'을 말하는 거짓 안심이 된다.)"""
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-sf")
        monkeypatch.setattr(remote_claims, "scan_remote_done", lambda *a, **k: ({}, "offline"))

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["start", TASK_ID]) == 0
        err = capsys.readouterr().err
        assert UNREADABLE in err
        assert "(offline)" in err

    def test_start_no_remote_is_silent_about_trunk(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-s6")
        _land_on_trunk(clone, monkeypatch, "lander-s6", "done")

        monkeypatch.chdir(mine)
        capsys.readouterr()
        assert cli.main(["start", TASK_ID, "--no-remote"]) == 0
        err = capsys.readouterr().err
        assert "이미 **" not in err
        assert UNREADABLE not in err


class TestScanFunction:
    """`scan_trunk_terminal` 단위 — 일부 ID만 종결일 때 정확히 그것만 돌려준다."""

    def test_returns_only_terminal_ids(self, bare_remote, monkeypatch):
        _, clone = bare_remote
        mine = _stale_session(clone, monkeypatch, "mine-u")
        _land_on_trunk(clone, monkeypatch, "lander-u", "done")
        _refresh_refs(mine)

        result = remote_claims.scan_trunk_terminal(mine, [TASK_ID, "T54-99-not-on-trunk"])
        assert result.status == "ok"
        assert set(result.found) == {TASK_ID}
        assert result.found[TASK_ID].trunk_status == "done"

    def test_empty_input_is_ok_and_empty(self, bare_remote):
        bare, _clone = bare_remote
        assert remote_claims.scan_trunk_terminal(bare, []).status == "ok"
