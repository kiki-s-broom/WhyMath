"""HARN-317 — 맨 번호 ID(슬러그 없음)의 예약 덮어쓰기 차단.

사고(task-id-collision 14·15회차): 두 세션이 슬러그 없는 같은 ID(`EOS-209` · `P3-93` · `P3-94`)로
**서로 다른** 태스크를 add했다. 예약(`number_guard.reserve`)과 번호 가드(`_id_number_conflict`)는
"full ID가 같으면 같은 태스크의 재등재"로 보고 통과시켰고, 뒤 세션이 앞 세션의 예약을 덮어썼다.

대책: 맨 번호 ID는 제목 지문이 같을 때만 같은 태스크로 본다. 모르면(옛 예약·claim·읽기 실패)
같다고 보지 않는다. 슬러그 있는 ID는 종전 판정 그대로다(대조군).

모든 절에 그 절이 없으면 통과해 버리는 입력(반례)과 대조군을 함께 둔다. 시임이 아니라 로컬 bare
원격의 실제 git push/fetch(`bare_remote` 픽스처)로 재현한다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import number_guard
import remote_claims
import store

import backlog as cli


def _add(task_id: str, title: str) -> int:
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
    repo = clone(name)
    monkeypatch.chdir(repo)
    assert cli.main(["seed"]) == 0
    return repo


def _git(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True)


def _push(repo: Path, branch: str) -> None:
    for argv in (
        ["add", "."],
        ["commit", "-q", "-m", "등재만 한 상태"],
        ["push", "--quiet", "-u", "origin", branch],
    ):
        assert _git(repo, *argv).returncode == 0, argv


def _reservation(repo: Path, number: str) -> dict:
    sha, status = remote_claims._fetch_claims_branch(repo)
    assert status == "ok" and sha
    out = _git(repo, "show", f"{sha}:reservations/{number}.json")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _legacy_add(monkeypatch, task_id: str, title: str) -> None:
    """예약을 남기지 않는 add — 구버전 하네스·예약 실패 세션의 모사(파일만 생긴다)."""
    with monkeypatch.context() as patch:
        patch.setattr(
            number_guard, "reserve", lambda *a, **k: number_guard.ReserveResult("skipped")
        )
        assert _add(task_id, title) == 0


# ── 순수 판정 ────────────────────────────────────────────────────────────────


class TestPureJudgement:
    def test_bare_id_detection(self):
        assert number_guard.is_bare_id("P3-93")
        assert number_guard.is_bare_id("HARN-317")
        assert not number_guard.is_bare_id("P3-93-some-slug")
        assert not number_guard.is_bare_id("not-an-id")

    def test_fingerprint_normalizes_whitespace_and_tells_titles_apart(self):
        fp = number_guard.title_fingerprint
        assert fp("개수형  답\n지원") == fp(" 개수형 답 지원 ")
        assert fp("개수형 답 지원") != fp("풀이 유형 승인 표")
        assert fp("") == "" and fp(None) == ""

    def test_same_task_rules(self):
        same = number_guard.same_task
        a, b = number_guard.title_fingerprint("A"), number_guard.title_fingerprint("B")
        assert not same("P3-93", "P3-94", a, a), "번호가 다르면 다른 태스크"
        assert same("P3-93-x", "P3-93-x", a, b), "슬러그 있는 같은 ID는 지문과 무관하게 같다"
        assert same("P3-93", "P3-93", a, a), "맨 번호 + 같은 지문 = 같은 태스크"
        assert not same("P3-93", "P3-93", a, b), "맨 번호 + 다른 지문 = 다른 태스크"
        assert not same("P3-93", "P3-93", a, ""), "지문을 모르면 같다고 보지 않는다"
        assert not same("P3-93", "P3-93", "", ""), "양쪽 다 몰라도 같다고 보지 않는다"


# ── 예약(CAS) 경로 — 14·15회차 재현 ────────────────────────────────────────────


class TestBareIdReservation:
    def test_other_session_same_bare_id_different_title_is_refused(
        self, bare_remote, monkeypatch, capsys
    ):
        """다른_세션의_같은_맨_번호_ID가_다른_제목이면_거부되고_앞_세션_예약이_남는다(15회차 재현)"""
        _, clone = bare_remote
        a = _session(clone, monkeypatch, "a")
        assert _add("S9-30", "개수형 답 finalize 지원") == 0
        before = _reservation(a, "S9-30")
        assert before["branch"] == "claude/a" and before.get("title_fp")

        b = _session(clone, monkeypatch, "b")
        capsys.readouterr()
        assert _add("S9-30", "풀이 유형 승인 표 집행") == 1, "15회차: 덮어쓰고 통과하면 안 된다"
        err = capsys.readouterr().err
        assert "HARN-317" in err and "S9-31" in err, "거부 사유와 다음 빈 번호를 말해야 한다"
        after = _reservation(b, "S9-30")
        assert after == before, "앞 세션의 예약이 덮어써지면 안 된다"
        backlog, _ = store.load_backlog(b)
        assert "S9-30" not in backlog.tasks

    def test_same_bare_id_same_title_from_another_clone_passes(self, bare_remote, monkeypatch):
        """같은_태스크(같은_제목)를_다른_클론에서_다시_등재하는_것은_통과(대조군)"""
        _, clone = bare_remote
        _session(clone, monkeypatch, "a")
        assert _add("S9-32", "같은 태스크의 재등재") == 0
        _session(clone, monkeypatch, "b")
        assert _add("S9-32", "같은 태스크의 재등재") == 0

    def test_reserve_cas_refuses_even_if_the_guard_was_skipped(self, bare_remote, monkeypatch):
        """번호_가드를_건너뛰어도_CAS_자체가_다른_제목의_맨_번호_예약을_거부한다(절 단독 반례)"""
        _, clone = bare_remote
        a = _session(clone, monkeypatch, "a")
        fa = number_guard.title_fingerprint("A 태스크")
        fb = number_guard.title_fingerprint("B 태스크")
        assert number_guard.reserve(a, "S9-34", "claude/a", fingerprint=fa).status == "ok"
        b = _session(clone, monkeypatch, "b")
        result = number_guard.reserve(b, "S9-34", "claude/b", fingerprint=fb)
        assert result.status == "conflict" and result.holder_branch == "claude/a"
        same = number_guard.reserve(b, "S9-34", "claude/b", fingerprint=fa)
        assert same.status == "ok", "같은 지문(같은 태스크)은 통과 — 대조군"

    def test_legacy_reservation_without_fingerprint_is_not_assumed_same(
        self, bare_remote, monkeypatch
    ):
        """지문_없는_옛_예약은_같은_태스크로_가정하지_않는다(모른다_≠_같다)"""
        _, clone = bare_remote
        a = _session(clone, monkeypatch, "a")
        assert number_guard.reserve(a, "S9-36", "claude/a").status == "ok"
        assert "title_fp" not in _reservation(a, "S9-36")
        b = _session(clone, monkeypatch, "b")
        fp = number_guard.title_fingerprint("아무 제목")
        assert number_guard.reserve(b, "S9-36", "claude/b", fingerprint=fp).status == "conflict"

    def test_same_branch_rerun_still_passes(self, bare_remote, monkeypatch):
        """같은_세션의_재실행은_지문과_무관하게_통과(종전_규칙_유지)"""
        _, clone = bare_remote
        a = _session(clone, monkeypatch, "a")
        fa = number_guard.title_fingerprint("첫 제목")
        fb = number_guard.title_fingerprint("고친 제목")
        assert number_guard.reserve(a, "S9-38", "claude/a", fingerprint=fa).status == "ok"
        assert number_guard.reserve(a, "S9-38", "claude/a", fingerprint=fb).status == "ok"

    def test_foreign_claim_on_same_bare_id_is_a_conflict(self, bare_remote, monkeypatch):
        """다른_세션의_같은_맨_번호_claim은_충돌(claim에는_지문이_없다)"""
        _, clone = bare_remote
        a = _session(clone, monkeypatch, "a")
        assert remote_claims.claim(a, "S9-40", "claude/a").status == "ok"
        b = _session(clone, monkeypatch, "b")
        fp = number_guard.title_fingerprint("다른 태스크")
        assert number_guard.reserve(b, "S9-40", "claude/b", fingerprint=fp).status == "conflict"
        # 대조군: 슬러그 있는 같은 full ID의 claim은 종전대로 같은 태스크
        assert remote_claims.claim(a, "S9-41-slugged", "claude/a").status == "ok"
        assert number_guard.reserve(b, "S9-41-slugged", "claude/b").status == "ok"


# ── 번호 가드(사전 검사) 경로 — 원격 브랜치 사본 ──────────────────────────────


class TestBareIdRemoteFile:
    def test_pushed_bare_id_with_different_title_is_refused(self, bare_remote, monkeypatch, capsys):
        """예약_없이_push된_같은_맨_번호_ID가_다른_제목이면_사전_검사가_거부한다(14회차 형태)"""
        _, clone = bare_remote
        a = _session(clone, monkeypatch, "a")
        _legacy_add(monkeypatch, "S9-42", "먼저 올린 태스크")
        _push(a, "claude/a")
        _session(clone, monkeypatch, "b")
        capsys.readouterr()
        assert _add("S9-42", "전혀 다른 태스크") == 1
        err = capsys.readouterr().err
        assert "HARN-317" in err and "claude/a" in err

    def test_pushed_bare_id_with_same_title_passes(self, bare_remote, monkeypatch):
        """같은_제목이면_같은_태스크의_다른_사본이다(대조군)"""
        _, clone = bare_remote
        a = _session(clone, monkeypatch, "a")
        _legacy_add(monkeypatch, "S9-44", "같은 태스크")
        _push(a, "claude/a")
        _session(clone, monkeypatch, "b")
        assert _add("S9-44", "같은 태스크") == 0


# ── ④ 슬러그 없는 ID 경고 ─────────────────────────────────────────────────────


class TestSlugWarning:
    def test_bare_id_add_warns_and_slugged_does_not(self, bare_remote, monkeypatch, capsys):
        _, clone = bare_remote
        _session(clone, monkeypatch, "a")
        capsys.readouterr()
        assert _add("S9-46", "슬러그 없음") == 0
        assert "슬러그 없는 ID 'S9-46'" in capsys.readouterr().err
        assert _add("S9-47-with-slug", "슬러그 있음") == 0
        assert "슬러그 없는 ID" not in capsys.readouterr().err
