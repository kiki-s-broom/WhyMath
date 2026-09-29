"""HARN-111 — 태스크 번호의 원격 예약(ⓐ)·스캔 전 갱신(ⓓ)·claim 슬러그 대조(⑦가나)·브랜치 발견 스탬프(⑦다).

사고 3종을 각각 **재현 → 대책 후 거부/고지**로 동결한다(시임이 아니라 로컬 bare 원격의 실제
git push/fetch/ls-tree — `bare_remote` 픽스처):

  · 3회차 EOS-108(24초) — 상대가 **push하지 않은** 번호. 파일명 스캔으로는 원리상 보이지 않는다
    (각 테스트가 그 전제를 먼저 단언한다). 예약이 막는다.
  · 4회차 EOS-128(19분) — 상대 브랜치가 origin에 있는데 이 클론에 ref가 없었다. 갱신이 막는다.
  · 의미 축 HARN-183↔OPS-69 — 본문이 어디에도 없고 claim 대장의 full ID만 있었다. 슬러그가 잡는다.
  · 신선도 고지 무력화 — claim fetch가 FETCH_HEAD를 새로 써서 종전 척도가 '방금'이 됐다.

모든 절에 **그 절이 없으면 통과해 버리는 입력**과 **대조군**을 함께 둔다(CLAUDE.md 2026-09-07·09-08).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import number_guard
import remote_claims
import store

import backlog as cli

_OFFLINE_STDERR = (
    "fatal: unable to access 'https://example.invalid/x.git/': "
    "Could not resolve host: example.invalid\n"
)


def _add(task_id: str, title: str = "번호 예약 테스트 태스크") -> int:
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


def _session(clone, monkeypatch, name: str) -> Path:
    """독립 세션 = 클론 + seed. cwd를 그 클론으로 옮긴다(CLI의 root는 cwd에서 정해진다)."""
    repo = clone(name)
    monkeypatch.chdir(repo)
    assert cli.main(["seed"]) == 0
    return repo


def _git(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True)


def _events(repo: Path, action: str) -> list[dict]:
    rows: list[dict] = []
    for path in store.event_paths(repo):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("action") == action:
                    rows.append(row)
    return rows


def _claims_tree_paths(repo: Path) -> list[str]:
    """origin의 claim 브랜치 트리 경로 전부 — 파싱이 아니라 원시 경로로 판정한다."""
    sha, status = remote_claims._fetch_claims_branch(repo)
    assert status == "ok" and sha, f"claim 브랜치 조회 실패: {status}"
    out = _git(repo, "ls-tree", "-r", "--name-only", sha)
    assert out.returncode == 0
    return out.stdout.split()


def _legacy_add(monkeypatch, task_id: str) -> None:
    """예약을 남기지 않는 add — 구버전 하네스 세션·예약 실패 세션의 모사."""
    with monkeypatch.context() as patch:
        patch.setattr(
            number_guard, "reserve", lambda *a, **k: number_guard.ReserveResult("skipped")
        )
        assert _add(task_id) == 0


def _push(repo: Path, branch: str) -> None:
    for argv in (
        ["checkout", "-q", "-B", branch],
        ["add", "."],
        ["commit", "-q", "-m", "등재만 한 상태"],
        ["push", "--quiet", "-u", "origin", branch],
    ):
        assert _git(repo, *argv).returncode == 0, argv


def _age_branch_stamp(repo: Path, seconds: float) -> None:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    common = _git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    path = Path(common) if Path(common).is_absolute() else repo / common
    (path / number_guard.STAMP_FILE).write_text(
        json.dumps({"ts": moment.strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8"
    )


def _fail_heads_fetch(monkeypatch) -> None:
    """전체 브랜치 갱신(ⓓ)만 실패시킨다 — claim fetch·예약 push는 그대로 성공한다."""
    real = remote_claims._git

    def fake(root, *argv, **kw):
        if argv and argv[0] == "fetch" and number_guard.HEADS_REFSPEC in argv:
            return subprocess.CompletedProcess(["git", *argv], 128, "", _OFFLINE_STDERR)
        return real(root, *argv, **kw)

    monkeypatch.setattr(remote_claims, "_git", fake)


# ── ⓐ 번호 예약 — 3회차(push 전 24초) ─────────────────────────────────────────


class TestPrePushReservation:
    def test_unpushed_number_is_reserved_and_blocks_the_other_session(
        self, bare_remote, monkeypatch, capsys
    ):
        """push_전_번호도_예약으로_보여_다른_세션의_add가_거부되고_다음_번호를_제안받는다"""
        _, clone = bare_remote
        _session(clone, monkeypatch, "a")
        capsys.readouterr()
        assert _add("S9-10-first-writer") == 0
        assert "번호 예약 S9-10" in capsys.readouterr().out, "예약 성공은 화면에 남아야 한다"

        b = _session(clone, monkeypatch, "b")
        # 전제(변별력): A는 push하지 않았다 — 파일명 스캔으로는 원리상 보이지 않는다
        files, status = remote_claims.scan_remote_task_files(b, fetch=True)
        assert status == "ok"
        assert not [f for f in files if f.task_id.startswith("S9-10")], "전제가 깨졌다"

        capsys.readouterr()
        assert _add("S9-10-second-writer") == 1, "push 전 번호를 못 보면 3회차 사고 그대로다"
        err = capsys.readouterr().err
        assert "S9-10-first-writer" in err and "원격 번호 예약(claude/a)" in err
        assert "S9-11" in err, "거부는 다음 빈 번호 제안(재선택)과 함께 와야 한다"
        backlog, _ = store.load_backlog(b)
        assert "S9-10-second-writer" not in backlog.tasks

    def test_distinct_numbers_pass_on_both_sessions(self, bare_remote, monkeypatch, capsys):
        """번호가_다르면_양쪽_다_통과 — 대조군(전부 거부하는 과잉 수정 방지)"""
        _, clone = bare_remote
        _session(clone, monkeypatch, "a")
        assert _add("S9-12-first") == 0
        _session(clone, monkeypatch, "b")
        capsys.readouterr()
        assert _add("S9-13-second") == 0
        assert "번호 충돌" not in capsys.readouterr().err

    def test_same_full_id_from_another_clone_is_not_a_conflict(self, bare_remote, monkeypatch):
        """같은_full_ID의_재예약은_충돌이_아니다(시딩·복제 세션 — HARN-10 규칙 승계)"""
        _, clone = bare_remote
        _session(clone, monkeypatch, "a")
        assert _add("S9-14-shared-task") == 0
        _session(clone, monkeypatch, "b")
        assert _add("S9-14-shared-task") == 0

    def test_cas_race_loser_is_refused_and_told_the_next_number(
        self, bare_remote, monkeypatch, capsys
    ):
        """번호_가드_통과_직후_남이_먼저_예약하면_CAS에서_지고_번호를_다시_고르게_된다

        24초 경합의 원자적 형태: 두 세션의 번호 가드가 **둘 다** 빈 번호를 봤다. 예약 CAS가
        정확히 한쪽만 통과시켜야 하고, 진 쪽은 fail-open으로 등재하지 않고 거부된다.
        """
        _, clone = bare_remote
        a = clone("a")
        b = _session(clone, monkeypatch, "b")
        real = number_guard.reserve

        def racing(root, task_id, branch, **kw):
            # B의 번호 가드가 통과한 **뒤**, B의 CAS **앞** — A가 같은 번호를 잡는다
            assert real(a, "S9-15-racer-a", "claude/a").status == "ok"
            return real(root, task_id, branch, **kw)

        monkeypatch.setattr(number_guard, "reserve", racing)
        tasks_dir = b / "backlog" / "tasks"
        before = sorted(p.name for p in tasks_dir.iterdir())
        capsys.readouterr()

        assert _add("S9-15-racer-b") == 1, "CAS에서 진 쪽이 등재되면 예약이 무의미하다"
        err = capsys.readouterr().err
        assert "S9-15-racer-a" in err and "S9-16" in err
        assert sorted(p.name for p in tasks_dir.iterdir()) == before, "거부인데 파일이 생겼다"
        conflicts = _events(b, "number_reserve_conflict")
        assert conflicts and conflicts[-1]["holder"] == "S9-15-racer-a"

    def test_claim_landing_between_guard_and_cas_also_refuses(
        self, bare_remote, monkeypatch, capsys
    ):
        """가드_통과_뒤_같은_번호의_claim이_생기면_같은_스냅샷에서_잡는다 (claim 절)"""
        _, clone = bare_remote
        a = clone("a")
        _session(clone, monkeypatch, "b")
        real = number_guard.reserve

        def racing(root, task_id, branch, **kw):
            assert remote_claims.claim(a, "S9-17-claimed-by-a", "claude/a").status == "ok"
            return real(root, task_id, branch, **kw)

        monkeypatch.setattr(number_guard, "reserve", racing)
        capsys.readouterr()
        assert _add("S9-17-mine") == 1
        assert "S9-17-claimed-by-a" in capsys.readouterr().err

    def test_same_branch_may_reuse_its_own_orphan_reservation(self, bare_remote, monkeypatch):
        """같은_세션이_실패한_add의_잔재_예약을_다른_슬러그로_다시_잡는_것은_허용된다

        두 절(번호 가드의 자기 예약 제외 · CAS의 같은 세션 허용)이 **각각** 없으면 이 입력이
        거부된다 — 각 절의 반례다. 다른 브랜치의 예약은 여전히 막힌다(첫 테스트가 대조군).
        """
        _, clone = bare_remote
        b = _session(clone, monkeypatch, "b")
        assert number_guard.reserve(b, "S9-18-first-slug", "claude/b").status == "ok"
        assert _add("S9-18-second-slug") == 0
        paths = _claims_tree_paths(b)
        assert "reservations/S9-18.json" in paths

    def test_reservation_survives_claim_ledger_writes(self, bare_remote, monkeypatch, capsys):
        """claim_쓰기가_예약_디렉터리를_지우지_않는다 (_write_claims 보존 절)

        종전 `_write_claims`는 루트 트리를 `claims/` 하나로 새로 지었다 — 예약 도입 후에는
        착수·해제 한 번에 모든 예약이 조용히 사라지는 구조가 된다.
        """
        _, clone = bare_remote
        _session(clone, monkeypatch, "a")
        assert _add("S9-20-reserved-by-a") == 0
        c = clone("c")
        assert remote_claims.claim(c, "S2-01", "claude/c").status == "ok"
        assert remote_claims.release(c, "S2-01", "claude/c").status == "ok"

        b = _session(clone, monkeypatch, "b")
        assert "reservations/S9-20.json" in _claims_tree_paths(b)
        capsys.readouterr()
        assert _add("S9-20-late") == 1
        assert "S9-20-reserved-by-a" in capsys.readouterr().err

    def test_reservation_write_preserves_claims(self, bare_remote, monkeypatch):
        """예약_쓰기가_claim_디렉터리를_지우지_않는다 (_write_reservations 보존 절)"""
        _, clone = bare_remote
        c = clone("c")
        assert remote_claims.claim(c, "S2-01", "claude/c").status == "ok"
        a = _session(clone, monkeypatch, "a")
        assert _add("S9-21-after-claim") == 0
        claims, status = remote_claims.list_claims(a)
        assert status == "ok"
        assert [x.task_id for x in claims] == ["S2-01"]
        assert "reservations/S9-21.json" in _claims_tree_paths(a)

    def test_expired_reservations_are_ignored_and_swept(self, bare_remote, monkeypatch):
        """TTL을_넘긴_예약은_번호를_붙잡지_않고_다음_쓰기에서_걷힌다"""
        _, clone = bare_remote
        a = clone("a")
        past = datetime.now(timezone.utc) - timedelta(hours=number_guard.RESERVATION_TTL_HOURS + 1)
        with monkeypatch.context() as patch:
            patch.setattr(number_guard, "_utcnow", lambda: past)
            assert number_guard.reserve(a, "S9-22-stale", "claude/a").status == "ok"
            assert number_guard.reserve(a, "S9-23-stale-too", "claude/a").status == "ok"

        b = _session(clone, monkeypatch, "b")
        assert _add("S9-22-fresh") == 0, "만료된 예약이 번호를 붙잡으면 번호가 영구 소모된다"
        paths = _claims_tree_paths(b)
        assert "reservations/S9-22.json" in paths
        assert "reservations/S9-23.json" not in paths, "만료 예약이 청소되지 않았다"

    def test_reservation_network_failure_is_named_and_counted_not_silent(
        self, bare_remote, monkeypatch, capsys
    ):
        """예약_push가_네트워크로_실패하면_상태를_말하고_이벤트를_남기되_등재는_진행한다"""
        _, clone = bare_remote
        b = _session(clone, monkeypatch, "b")
        monkeypatch.setattr(
            remote_claims,
            "_push_claims",
            lambda root, base, commit: subprocess.CompletedProcess(
                ["git", "push"], 128, "", _OFFLINE_STDERR
            ),
        )
        capsys.readouterr()
        assert (
            _add("S9-24-offline") == 0
        ), "확정 신호가 아닌 실패는 등재를 막지 않는다(start와 동일)"
        err = capsys.readouterr().err
        assert "번호 예약 실패(offline)" in err
        assert "https://" not in err, "stderr 인용에서 URL은 가려야 한다"
        rows = _events(b, "number_reserve_unavailable")
        assert rows and rows[-1]["status"] == "offline"
        backlog, _ = store.load_backlog(b)
        assert "S9-24-offline" in backlog.tasks


# ── ⓓ 스캔 전 갱신 — 4회차(19분) ─────────────────────────────────────────────


class TestRefreshBeforeScan:
    def test_branch_pushed_after_clone_is_seen(self, bare_remote, monkeypatch, capsys):
        """내가_클론한_뒤에_push된_브랜치의_번호도_본다 — EOS-128 재현"""
        _, clone = bare_remote
        newcomer = _session(clone, monkeypatch, "newcomer")  # 먼저 클론 — 이후 fetch 없음
        other = _session(clone, monkeypatch, "other")
        _legacy_add(monkeypatch, "S9-30-other-task")
        _push(other, "claude/other")

        monkeypatch.chdir(newcomer)
        # 전제(변별력): 이 클론에는 그 브랜치의 ref가 없다
        assert _git(newcomer, "rev-parse", "--verify", "--quiet", "origin/claude/other").returncode
        capsys.readouterr()
        assert _add("S9-30-mine") == 1, "origin에 19분 전부터 있던 번호를 놓치면 4회차 그대로다"
        assert "원격 브랜치 backlog/tasks/(claude/other)" in capsys.readouterr().err

    def test_refresh_failure_is_named_counted_and_marks_a_partial_verdict(
        self, bare_remote, monkeypatch, capsys
    ):
        """갱신_실패는_원인과_함께_경고하고_이벤트를_남기며_부분_판정이라고_말한다"""
        _, clone = bare_remote
        n = _session(clone, monkeypatch, "n")
        _fail_heads_fetch(monkeypatch)
        capsys.readouterr()
        assert _add("S9-31-refresh-down") == 0
        captured = capsys.readouterr()
        assert "원격 브랜치 목록 갱신 실패(offline" in captured.err
        assert "<url>" in captured.err, "실패 원인(stderr 한 줄)이 남아야 한다"
        assert "부분 판정" in captured.out, "다 보지 못한 판정을 통과와 같은 색으로 두면 안 된다"
        rows = _events(n, "remote_heads_refresh_failed")
        assert rows and rows[-1]["status"] == "offline"

    def test_scan_that_finds_no_refs_is_a_failure_not_a_pass(self, bare_remote, monkeypatch):
        """스캔_0건은_판정_불가로_계상된다 — 대조군은_backlog가_있는_브랜치를_본_경우"""
        _, clone = bare_remote
        other = _session(clone, monkeypatch, "other")
        _legacy_add(monkeypatch, "S9-32-other-task")
        _push(other, "claude/other")

        n = clone("n")
        good = number_guard.observe(n)
        assert good.files_status == "ok" and good.complete, good  # 대조군

        # 좁은 클론 + 갱신 실패 = 볼 ref가 0개 — 4회차의 환경 조건
        for ref in _git(
            n, "for-each-ref", "--format=%(refname)", "refs/remotes/origin"
        ).stdout.split():
            assert _git(n, "update-ref", "-d", ref).returncode == 0
        _fail_heads_fetch(monkeypatch)
        bad = number_guard.observe(n)
        assert bad.files_status == "empty" and not bad.complete, bad
        assert any("스캔 0건" in w and "판정 불가" in w for w in bad.warnings())


class TestUnknownIsNotFoldedIntoNone:
    def test_claim_ledger_failure_status_is_named_not_counted_as_zero_claims(
        self, bare_remote, monkeypatch, capsys
    ):
        """claim_대장_조회_실패_상태를_버리지_않는다 — 종전엔 '원격 claim 0건'으로 조용히 접혔다

        `list_claims`는 예외를 스스로 삼키고 `([], "offline"|"error")`를 돌려준다. 종전 호출부는
        그 상태를 `_status`로 버렸고, 바깥 `except`는 발화할 수 없는 구조였다. 그래서 예외가 아니라
        **상태값**으로 주입해야 실제 실패 경로를 탄다(예외 주입은 이 결함을 못 본다).
        """
        _, clone = bare_remote
        _session(clone, monkeypatch, "n")
        monkeypatch.setattr(remote_claims, "list_claims", lambda root, *a, **k: ([], "error"))
        capsys.readouterr()
        assert _add("S9-33-ledger-down") == 0, "조회 실패는 등재를 막지 않는다(fail-open)"
        captured = capsys.readouterr()
        assert "원격 claim 대장 조회 실패(error)" in captured.err
        assert "부분 판정" in captured.out


# ── ⑦(가)(나) claim 대장 슬러그 대조 — HARN-183↔OPS-69 ─────────────────────────


_INCIDENT_SLUG = "harness-integrity-timeout-budget"


class TestClaimSlugNotice:
    def test_claim_only_task_with_the_same_slug_is_noticed(self, bare_remote, monkeypatch, capsys):
        """본문이_어디에도_없고_claim_full_ID만_있는_태스크도_슬러그로_고지된다"""
        _, clone = bare_remote
        holder = clone("holder")
        claimed = f"ZY-69-{_INCIDENT_SLUG}"
        assert (
            remote_claims.claim(holder, claimed, "claude/harness-integrity-timeout").status == "ok"
        )
        n = _session(clone, monkeypatch, "n")
        # 전제(수정 전 경로의 실패 재현): 그 태스크는 어느 원격 브랜치 사본에도 없다 —
        # 본문 대조(HARN-51)의 대조군에 오를 방법이 원리상 없다
        files, status = remote_claims.scan_remote_task_files(n, fetch=True)
        assert status == "ok" and not [f for f in files if f.task_id == claimed]

        capsys.readouterr()
        assert _add(f"ZZ-83-{_INCIDENT_SLUG}", "잡 시간 제한이 실행 편차 안쪽에 들어왔다") == 0
        err = capsys.readouterr().err
        assert claimed in err and "슬러그 대조" in err and "원격 claim" in err

    def test_unrelated_claim_slug_stays_silent(self, bare_remote, monkeypatch, capsys):
        """무관한_슬러그의_claim은_고지하지_않는다 — 대조군(항상 뜨는 고지는 소음이다)"""
        _, clone = bare_remote
        holder = clone("holder")
        assert (
            remote_claims.claim(holder, "ZY-70-ocr-fraction-bar-detection", "claude/x").status
            == "ok"
        )
        _session(clone, monkeypatch, "n")
        capsys.readouterr()
        assert _add(f"ZZ-84-{_INCIDENT_SLUG}") == 0
        err = capsys.readouterr().err
        assert "슬러그 대조" not in err and "ZY-70" not in err

    def test_reserved_but_unpushed_slug_is_noticed(self, bare_remote, monkeypatch, capsys):
        """push_전_예약의_슬러그도_고지된다 — 번호가 달라도 같은 문제(의미 축의 24초 사각)"""
        _, clone = bare_remote
        _session(clone, monkeypatch, "a")
        assert _add("ZZ-85-branch-discovery-freshness-stamp") == 0
        _session(clone, monkeypatch, "b")
        capsys.readouterr()
        assert _add("ZZ-86-branch-discovery-freshness-stamp") == 0
        err = capsys.readouterr().err
        assert "ZZ-85-branch-discovery-freshness-stamp" in err and "원격 번호 예약" in err

    def test_notice_reuses_the_ledger_the_number_guard_read(self, bare_remote, monkeypatch):
        """고지는_번호_가드가_읽은_claim_대장을_재사용한다 — claim 대장 조회는 add 한 번에 1회"""
        _, clone = bare_remote
        holder = clone("holder")
        assert remote_claims.claim(holder, f"ZY-71-{_INCIDENT_SLUG}", "claude/h").status == "ok"
        _session(clone, monkeypatch, "n")
        calls: list[Path] = []
        real = remote_claims.list_claims

        def spy(root, *a, **kw):
            calls.append(root)
            return real(root, *a, **kw)

        monkeypatch.setattr(remote_claims, "list_claims", spy)
        assert _add(f"ZZ-87-{_INCIDENT_SLUG}") == 0
        assert len(calls) == 1, f"claim 대장을 {len(calls)}회 조회했다 — 고지가 다시 읽고 있다"


# ── ⑦(다) 브랜치 발견 스탬프 ────────────────────────────────────────────────


class TestBranchDiscoveryStamp:
    def test_claim_fetch_moves_the_old_gauge_but_not_the_branch_stamp(self, bare_remote):
        """claim_fetch는_종전_척도를_'방금'으로_만들지만_브랜치_스탬프는_건드리지_않는다

        양방향: 종전 척도(`remote_refs_age_seconds`)는 claim fetch 하나로 0초가 된다 — 그래서
        add 안에서 신선도 고지가 구조적으로 안 켜졌다(수정 전 미검출). 새 척도는 3시간을 유지한다.
        """
        _, clone = bare_remote
        holder = clone("holder")
        assert remote_claims.claim(holder, "S2-01", "claude/holder").status == "ok"
        n = clone("n")
        three_hours = 3 * 3600
        _age_branch_stamp(n, three_hours)
        aged = time.time() - three_hours
        for trace in ("FETCH_HEAD", "packed-refs", "refs/remotes/origin"):
            if (n / ".git" / trace).exists():
                os.utime(n / ".git" / trace, (aged, aged))
        assert (remote_claims.remote_refs_age_seconds(n)[0] or 0) >= three_hours - 60  # 전제

        claims, status = remote_claims.list_claims(n)
        assert status == "ok" and claims, "claim fetch가 실제로 돌아야 이 테스트가 성립한다"

        old_age, _ = remote_claims.remote_refs_age_seconds(n)
        new_age, new_status = number_guard.branch_snapshot_age(n)
        assert (
            old_age is not None and old_age < 60
        ), "종전 척도가 claim fetch에 속지 않았다면 전제가 틀렸다"
        assert new_status == "ok" and new_age is not None and new_age >= three_hours - 60

    def test_successful_refresh_stamps_now_and_notice_stays_quiet(
        self, bare_remote, monkeypatch, capsys
    ):
        """갱신이_성공하면_스탬프가_지금이_되고_신선도_고지는_침묵한다 — 대조군"""
        _, clone = bare_remote
        n = _session(clone, monkeypatch, "n")
        _age_branch_stamp(n, 3 * 3600)
        capsys.readouterr()
        assert _add("S9-40-fresh") == 0
        assert "원격 스냅샷이" not in capsys.readouterr().err
        age, status = number_guard.branch_snapshot_age(n)
        assert status == "ok" and age is not None and age < 60

    def test_stamp_is_shared_through_the_common_git_dir(self, bare_remote, tmp_path):
        """linked_worktree에서_갱신해도_주_클론이_같은_스탬프를_읽는다(ref는 공용이므로)"""
        _, clone = bare_remote
        n = clone("n")
        worktree = tmp_path / "linked-wt"
        assert _git(n, "worktree", "add", "-q", "--detach", str(worktree), "HEAD").returncode == 0
        assert number_guard.branch_snapshot_age(n) == (None, "no-stamp")  # 전제: 스탬프 없음
        assert number_guard.refresh_remote_heads(worktree)[0] == "ok"
        age, status = number_guard.branch_snapshot_age(n)
        assert status == "ok" and age is not None and age < 60

    def test_age_reader_never_fetches(self, bare_remote, monkeypatch):
        """스탬프_읽기는_네트워크를_타지_않는다 — 고지 헬퍼의 비용 계약(HARN-43) 승계"""
        _, clone = bare_remote
        n = clone("n")
        seen: list[tuple[str, ...]] = []
        real = remote_claims._git

        def spy(root, *argv, **kw):
            seen.append(argv)
            return real(root, *argv, **kw)

        monkeypatch.setattr(remote_claims, "_git", spy)
        number_guard.branch_snapshot_age(n)
        assert seen, "git을 한 번도 부르지 않았다면 이 감시 자체가 무효다"
        assert not [a for a in seen if a and a[0] in ("fetch", "ls-remote", "push")], seen


# ── claim 브랜치 트리 보존 — HARN-36 치유 계약과의 정합 ─────────────────────────


class TestRootTreePreservation:
    def test_claim_write_keeps_reservations_but_heals_cr_polluted_claims_dir(self, bare_remote):
        """다른_디렉터리는_옮기고_CR_오염된_claims_디렉터리는_옮기지_않는다

        보존 절이 `claims\\r`까지 옮기면 HARN-36의 "다음 뮤테이션이 오염을 치유한다"가 깨진다
        — 보존과 치유를 한 입력에서 함께 잰다(절마다 그 절의 반례).
        """
        _, clone = bare_remote
        a = clone("a")

        def blob(text: str) -> str:
            return remote_claims._git(
                a, "hash-object", "-w", "--stdin", input_text=text
            ).stdout.strip()

        def tree(lines: str) -> str:
            out = remote_claims._git(a, "mktree", input_text=lines)
            assert out.returncode == 0, out.stderr
            return out.stdout.strip()

        polluted = tree(f"100644 blob {blob('{}')}\tS2-01.json\r\n")
        reservations = tree(f"100644 blob {blob('{}')}\tS9-50.json\n")
        root_tree = tree(
            f"040000 tree {polluted}\tclaims\r\n040000 tree {reservations}\treservations\n"
        )
        base = remote_claims._git(
            a, "commit-tree", root_tree, "-m", "base", env_extra=remote_claims._COMMIT_IDENTITY
        ).stdout.strip()
        mine = remote_claims.RemoteClaim("S2-02", "", "claude/a", "", {"task": "S2-02"})
        commit = remote_claims._write_claims(a, base, [mine], "claim S2-02")
        raw = remote_claims._git(a, "ls-tree", "-r", "-z", "--name-only", commit).stdout
        paths = [p for p in raw.split("\0") if p]
        assert "reservations/S9-50.json" in paths, "보존 절이 예약을 옮기지 않았다"
        assert "claims/S2-02.json" in paths
        assert not [p for p in paths if "\r" in p], f"CR 오염이 옮겨졌다: {paths!r}"
