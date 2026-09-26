"""HARN-176 — main 낡음·미머지 실시간 감시기의 변별력 동결.

**왜 양방향인가 (acceptance ⑥)**: "주의"만 확인하면 무엇에든 주의를 내는 감시기도
통과하고, "정상"만 확인하면 아무것도 못 보는 감시기도 통과한다. 그래서 핵심 판정마다
**같은 픽스처에서 상태 하나만 바꾼 쌍**을 둔다:

  · 뒤처짐 있음 / 없음                  — TestBehind
  · 체크아웃 전환 이벤트 있음 / 없음      — TestWatchEvents
  · main 전진 이벤트 있음 / 없음          — TestWatchEvents
  · fetch 실패(미측정) / 성공(정상)       — TestMeasurementFailure

그 밖에 읽기 전용(④ — 실행 전후 HEAD·로컬 브랜치·작업 트리·index 바이트가 같다),
cp949 리다이렉트에서 죽지 않음(⑤), PR 축(HARN-30 경유)·원격 브랜치 축(HARN-47 경유)의
위임과 실패 보존을 본다.

**hermetic** — 원격은 임시 폴더의 bare 저장소다. GitHub API는 부르지 않는다(PR 축은
`pr_delivery_audit._get`를 가짜로 바꿔 본다). 네트워크 0.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ops" / "main_watch.py"

_spec = importlib.util.spec_from_file_location("main_watch", _SCRIPT)
assert _spec and _spec.loader
mw = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mw  # @dataclass가 모듈을 조회하므로 exec 전에 등록한다
_spec.loader.exec_module(mw)

# 로컬 축만 — PR·원격 브랜치 축을 끄면 GitHub API 호출이 0회다.
LOCAL_ONLY = ("--skip", "prs", "--skip", "branches")
TRUNK_REF = "refs/remotes/origin/main"


# ─────────────────────────────────────────────────────────────────────────
# 픽스처 — bare 원격 + 감시 대상 클론(work) + 원격을 전진시키는 다른 세션(pusher)
# ─────────────────────────────────────────────────────────────────────────


def _git(cwd: Path, *argv: str) -> str:
    result = subprocess.run(
        ["git", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _identity(path: Path) -> None:
    _git(path, "config", "user.email", "test@whymath.local")
    _git(path, "config", "user.name", "main-watch-test")


@dataclass
class Repos:
    bare: Path
    work: Path  # 감시 대상 — main을 체크아웃한 클론
    pusher: Path  # 다른 세션 모사 — 원격 main을 전진시킨다

    def advance_main(self, *subjects: str) -> str:
        for subject in subjects or ("feat: 원격 전진",):
            _git(self.pusher, "commit", "-q", "--allow-empty", "-m", subject)
        _git(self.pusher, "push", "-q", "origin", "HEAD:main")
        return _git(self.pusher, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path: Path) -> Repos:
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    pusher = tmp_path / "pusher"
    _git(tmp_path, "clone", "-q", str(bare), str(pusher))
    _identity(pusher)
    (pusher / "README.md").write_text("seed\n", encoding="utf-8")
    (pusher / "a.txt").write_text("a\n", encoding="utf-8")
    _git(pusher, "add", ".")
    _git(pusher, "commit", "-q", "-m", "init")
    _git(pusher, "push", "-q", "origin", "main")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(bare), str(work))
    _identity(work)
    return Repos(bare=bare, work=work, pusher=pusher)


def _cli(repo: Path, *args: str, env_extra: dict[str, str] | None = None):
    """감시기를 별도 프로세스로 1회 실행 — 토큰 환경변수는 지워 GitHub 호출을 막는다."""
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    env["PYTHONUTF8"] = "1"
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(repo), "--no-gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )


class _Out(io.StringIO):
    """isatty를 흉내 내는 출력 — 터미널/파일에 따라 하트비트 모양이 달라진다."""

    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _watch(
    repos: Repos,
    cycles: int,
    between: Callable[[int], None] | None = None,
    *,
    tty: bool = False,
) -> tuple[str, int]:
    """감시 루프를 같은 프로세스에서 `cycles`주기 돌린다 — 주기 사이에 `between(n)`을 실행."""
    out = _Out(tty)
    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if between is not None:
            between(calls["n"])

    code = mw.watch(
        repos.work,
        mw.Options(skip=frozenset(mw.AXES)),
        trunk_ref=TRUNK_REF,
        interval=0,
        slow_interval=3600,
        out=out,
        sleep=fake_sleep,
        clock=lambda: "12:00:00",
        max_cycles=cycles,
    )
    return out.getvalue(), code


# ─────────────────────────────────────────────────────────────────────────
# ① 뒤처짐 있음 / 없음
# ─────────────────────────────────────────────────────────────────────────


class TestBehind:
    def test_fresh_main_checkout_is_ok(self, repos: Repos):
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[정상] 현재 체크아웃: main @" in r.stdout
        assert "origin/main과 같음" in r.stdout
        assert "[정상] 원격 가져오기: 성공" in r.stdout

    def test_main_checkout_behind_origin_is_attention(self, repos: Repos):
        repos.advance_main()
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[주의] 현재 체크아웃: main @" in r.stdout
        assert "origin/main보다 1커밋 뒤처짐" in r.stdout
        assert "git pull --ff-only" in r.stdout

    def test_local_main_behind_while_on_other_branch_is_reported_not_alarmed(self, repos: Repos):
        """main이 아닌 브랜치에 있으면 로컬 main의 낡음은 '당장 영향 없음'으로 수치만 보인다."""
        _git(repos.work, "switch", "-q", "-c", "side")
        _git(repos.work, "push", "-q", "-u", "origin", "side")
        repos.advance_main()
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[정상] 로컬 main 브랜치: origin/main보다 1커밋 뒤처짐" in r.stdout
        assert "[정상] 현재 체크아웃: side @" in r.stdout

    def test_feature_branch_drift_threshold_is_the_flow_health_constant(self):
        """표류 임계는 새로 만들지 않고 GIT-01 실측값(flow_health.DRIFT_BEHIND)을 쓴다."""
        sys.path.insert(0, str(_REPO_ROOT / "scripts" / "ops"))
        import flow_health  # noqa: PLC0415

        assert mw.DRIFT_BEHIND == flow_health.DRIFT_BEHIND
        below = mw._local_signals(_facts(head_behind=mw.DRIFT_BEHIND - 1), mw.Options())
        at = mw._local_signals(_facts(head_behind=mw.DRIFT_BEHIND), mw.Options())
        assert _signal(below, "head").state == mw.OK
        assert _signal(at, "head").state == mw.ATTENTION
        assert "표류" in _signal(at, "head").detail


def _facts(**overrides) -> mw.LocalFacts:
    base = {
        "fetch_state": "ok",
        "fetch_seconds": 0.1,
        "ref_age_seconds": 0.0,
        "trunk_ref": TRUNK_REF,
        "trunk_sha": "a" * 40,
        "trunk_subject": "subject",
        "head_branch": "feat",
        "head_sha": "b" * 40,
        "head_ahead": 1,
        "head_behind": 0,
        "head_upstream": "origin/feat",
        "head_unpushed": 0,
        "dirty_tracked": 0,
        "dirty_untracked": 0,
    }
    base.update(overrides)
    return mw.LocalFacts(**base)


def _signal(signals, key: str):
    return next(s for s in signals if s.key == key)


# ─────────────────────────────────────────────────────────────────────────
# ② 실시간 — 변화 이벤트 (체크아웃 전환·main 전진) 있음 / 없음
# ─────────────────────────────────────────────────────────────────────────


class TestWatchEvents:
    def test_branch_switch_emits_attention_event(self, repos: Repos):
        def switch(n: int) -> None:
            if n == 1:
                _git(repos.work, "switch", "-q", "-c", "other")

        out, _ = _watch(repos, 2, switch)
        assert "[12:00:00] [주의] 체크아웃 전환: main → other" in out

    def test_no_switch_emits_no_switch_event_but_a_heartbeat(self, repos: Repos):
        out, code = _watch(repos, 2)
        assert "체크아웃 전환" not in out
        assert "[12:00:00] 변화 없음 | main " in out
        assert code == 0

    def test_trunk_advance_emits_event_with_new_commit_subjects(self, repos: Repos):
        def advance(n: int) -> None:
            if n == 1:
                repos.advance_main("feat: 원격 전진 (#42)")

        out, code = _watch(repos, 2, advance)
        assert "[변화] origin/main 전진:" in out
        assert "feat: 원격 전진 (#42)" in out  # 새 커밋 제목이 세부 줄로 보인다
        # main 체크아웃이 뒤처지는 순간이 신호 전이 이벤트로도 보인다
        assert "현재 체크아웃: 정상 → 주의" in out
        assert code == 1

    def test_no_advance_emits_no_trunk_event(self, repos: Repos):
        out, _ = _watch(repos, 3)
        assert "전진" not in out
        assert out.count("변화 없음") == 2

    def test_trunk_rewrite_is_flagged_not_counted_as_progress(self, repos: Repos):
        repos.advance_main("feat: 하나", "feat: 둘")
        _git(repos.work, "pull", "-q", "--ff-only")

        def rewrite(n: int) -> None:
            if n == 1:
                _git(repos.pusher, "reset", "-q", "--hard", "HEAD~1")
                _git(repos.pusher, "commit", "-q", "--allow-empty", "-m", "feat: 다른 역사")
                _git(repos.pusher, "push", "-q", "-f", "origin", "HEAD:main")

        out, _ = _watch(repos, 2, rewrite)
        assert "[주의] origin/main 이력이 바뀌었다" in out
        assert "전진:" not in out

    def test_tty_heartbeat_overwrites_one_line_at_fixed_width(self, repos: Repos):
        out, _ = _watch(repos, 3, tty=True)
        beats = [seg for seg in out.split("\r")[1:]]
        assert len(beats) == 2
        for beat in beats:
            body = beat.rstrip("\n")
            assert "변화 없음" in body
            assert sum(mw._char_width(ch) for ch in body) == mw.HEARTBEAT_WIDTH
            # 모호 폭 문자('·' 등)는 콘솔마다 1칸/2칸이 달라 덮어쓰기 폭 계산을 깨뜨린다
            assert all(unicodedata.east_asian_width(ch) != "A" for ch in body), body
        assert out.endswith("\n"), "끝난 뒤에는 덮어쓰던 줄을 닫아야 한다"

    def test_carried_slow_axis_failure_is_not_repeated_every_fast_cycle(self, repos: Repos):
        """느린 축(PR)의 이어지는 '미측정'은 매분 실패 줄로 되풀이하지 않는다 — 습관화 방지.

        대신 하트비트 끝의 '미측정 N'으로 계속 보이고(침묵 아님), 느린 주기에 다시 재서
        또 실패하면 그때 실패 줄을 낸다. 여기서 PR 축은 저장소 이름을 몰라 항상 실패한다.
        """
        out = _Out(False)
        times = iter([0.0, 10.0, 20.0, 4000.0])  # 4주기째에만 느린 축 주기(3600초)가 돌아온다
        code = mw.watch(
            repos.work,
            mw.Options(skip=frozenset({"branches"}), repo_slug=""),
            trunk_ref=TRUNK_REF,
            interval=0,
            slow_interval=3600,
            out=out,
            sleep=lambda _s: None,
            now=lambda: next(times),
            clock=lambda: "12:00:00",
            max_cycles=4,
        )
        text = out.getvalue()
        assert text.count("[12:00:00] [미측정] 열린 PR") == 1  # 느린 주기(4주기째)에서만
        beats = [line for line in text.splitlines() if "변화 없음" in line]
        assert len(beats) == 2 and all(line.endswith("| 미측정 1") for line in beats), beats
        assert code == 2

    def test_file_heartbeat_is_one_line_per_quiet_cycle(self, repos: Repos):
        out, _ = _watch(repos, 3, tty=False)
        assert "\r" not in out
        assert out.count("\n[12:00:00] 변화 없음") == 2


def test_fit_width_counts_hangul_as_two_columns():
    assert mw.fit_width("가나다abc", 6) == "가나다"
    assert mw.fit_width("가나다abc", 7) == "가나다a"
    assert mw.fit_width("ab", 5) == "ab   "
    long = "변화 없음 · main abcdef0 · " * 5
    assert sum(mw._char_width(ch) for ch in mw.fit_width(long, 78)) == 78


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 신호(SIGINT)로 Ctrl+C를 모사한다")
def test_ctrl_c_ends_the_watch_cleanly_with_exit_0(repos: Repos, tmp_path: Path):
    """② Ctrl+C는 정상 종료다 — 트레이스백 없이 '감시 종료' 줄과 종료 코드 0.

    SIGINT를 **기본 동작으로 되돌려** 띄운다. 비대화형 셸이 `&`로 띄운 프로세스는 SIGINT가
    '무시'로 상속되고, 그러면 파이썬은 Ctrl+C 처리기를 아예 설치하지 않는다(2026-09-26
    런북 시뮬레이션에서 이것 때문에 첫 모사가 무효였다). 그 상태로 재면 이 테스트는
    감시기가 아니라 하네스의 신호 상속을 재게 된다.
    """
    log = tmp_path / "watch.log"
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    env["PYTHONUTF8"] = "1"
    cmd = [
        sys.executable,
        str(_SCRIPT),
        "--repo-root",
        str(repos.work),
        "--no-gh",
        "--watch",
        "--interval",
        "10",
        *LOCAL_ONLY,
    ]
    with log.open("wb") as out:
        proc = subprocess.Popen(
            cmd,
            stdout=out,
            stderr=subprocess.STDOUT,
            env=env,
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
        )
        try:
            deadline = time.monotonic() + 60
            while "감시 시작" not in log.read_text(encoding="utf-8", errors="replace"):
                assert proc.poll() is None, log.read_text(encoding="utf-8", errors="replace")
                assert time.monotonic() < deadline, "60초 안에 감시가 시작되지 않았다"
                time.sleep(0.2)
            proc.send_signal(signal.SIGINT)
            code = proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
    text = log.read_text(encoding="utf-8", errors="replace")
    assert code == 0, text
    assert text.rstrip().endswith("감시 종료(Ctrl+C)"), text
    assert "Traceback" not in text


def test_standalone_run_leaves_no_bytecode_cache(tmp_path: Path):
    """④ 흔적 없음 — 단독 실행은 `__pycache__`도 쓰지 않는다.

    실측(2026-09-26 런북 시뮬레이션): 캐시가 전용 worktree를 '미추적 파일 있음'으로 만들어
    정리 단계의 `git worktree remove`가 거부됐다. 스크립트 사본을 임시 폴더에 두고 돌려
    그 폴더에 캐시가 생기지 않는지 본다(저장소 원본은 다른 테스트가 이미 캐시를 만든다).
    """
    copy = tmp_path / "code"
    for sub in ("harness", "ops"):
        src = _REPO_ROOT / "scripts" / sub
        dst = copy / "scripts" / sub
        dst.mkdir(parents=True)
        for path in src.glob("*.py"):
            (dst / path.name).write_bytes(path.read_bytes())
    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    r = subprocess.run(
        [sys.executable, str(copy / "scripts" / "ops" / "main_watch.py"), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr  # --help는 sibling import 이후에 끝난다
    caches = sorted(p.relative_to(copy) for p in copy.rglob("__pycache__"))
    assert caches == [], f"감시기가 바이트코드 캐시를 남겼다: {caches}"


# ─────────────────────────────────────────────────────────────────────────
# ③ 측정 실패 ≠ 이상 없음
# ─────────────────────────────────────────────────────────────────────────


class TestMeasurementFailure:
    def test_fetch_failure_is_unmeasured_and_exit_2(self, repos: Repos, tmp_path: Path):
        _git(repos.work, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "[미측정] 원격 가져오기: 실패" in r.stdout
        # 뒤처짐 수치에는 '언제의 원격 기준인가'가 붙는다 — 못 봤음 ≠ 안 바뀜
        assert "(원격 기준: 방금 전)" in r.stdout
        assert "측정 실패 포함" in r.stdout

    def test_failed_cycles_print_a_failure_line_not_a_heartbeat(self, repos: Repos, tmp_path: Path):
        def break_origin(n: int) -> None:
            if n == 1:
                _git(repos.work, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

        out, code = _watch(repos, 3, break_origin)
        assert "원격 가져오기: 정상 → 미측정" in out
        # 실패가 이어진 3주기째에도 실패 줄이 나와야 한다(전이 이벤트가 없어도)
        assert out.count("[12:00:00] [미측정] 원격 가져오기") == 2
        assert "변화 없음" not in out
        assert code == 2

    def test_healthy_cycles_have_no_failure_line(self, repos: Repos):
        out, code = _watch(repos, 3)
        assert "[미측정]" not in out
        assert code == 0

    def test_internal_error_in_one_cycle_is_reported_and_the_watch_survives(
        self, repos: Repos, monkeypatch
    ):
        real = mw.take_snapshot
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("주입된 오류")
            return real(*args, **kwargs)

        monkeypatch.setattr(mw, "take_snapshot", flaky)
        out, code = _watch(repos, 3)
        assert "[12:00:00] [미측정] 감시기 내부 오류 — RuntimeError: 주입된 오류" in out
        # 오류 다음 주기는 다시 정상으로 돈다 — 감시가 죽지 않았다
        assert out.index("감시기 내부 오류") < out.index("변화 없음")
        assert code == 0

    def test_internal_error_in_one_shot_is_exit_2_not_1(self, repos: Repos, monkeypatch, capsys):
        """트레이스백으로 끝나면 종료 코드 1 — '주의 필요'와 같은 값이라 위장이 된다."""

        def broken(*args, **kwargs):
            raise RuntimeError("주입된 오류")

        monkeypatch.setattr(mw, "take_snapshot", broken)
        code = mw.main(["--repo-root", str(repos.work), "--no-gh", *LOCAL_ONLY])
        assert code == 2
        assert "감시기 내부 오류(RuntimeError: 주입된 오류)" in capsys.readouterr().err

    def test_no_fetch_with_fresh_refs_is_skipped_not_unmeasured(self, repos: Repos):
        r = _cli(repos.work, "--no-fetch", *LOCAL_ONLY)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[생략] 원격 가져오기" in r.stdout
        assert "[정상] 원격 기준 시점: 원격 ref 방금 전 기준" in r.stdout

    def test_no_fetch_with_stale_refs_is_unmeasured(self, repos: Repos):
        git_dir = repos.work / ".git"
        old = time.time() - 2 * 3600
        stamps = [git_dir / "FETCH_HEAD", git_dir / "packed-refs", git_dir / "refs/remotes/origin"]
        touched = [p for p in stamps if p.exists()]
        assert touched, "원격 ref 흔적이 하나도 없다 — 픽스처가 이 검사를 밟지 못한다"
        for path in touched:
            os.utime(path, (old, old))
        r = _cli(repos.work, "--no-fetch", *LOCAL_ONLY)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "[미측정] 원격 기준 시점" in r.stdout
        assert "낡아 main 비교를 믿을 수 없다" in r.stdout


def test_exit_code_precedence_unmeasured_over_attention():
    def sig(state: str) -> mw.Signal:
        return mw.Signal(state, "main", state, state, "")

    assert mw.exit_code([sig(mw.ATTENTION), sig(mw.UNMEASURED)]) == 2
    assert mw.exit_code([sig(mw.ATTENTION), sig(mw.OK)]) == 1
    assert mw.exit_code([sig(mw.OK), sig(mw.SKIPPED)]) == 0


# ─────────────────────────────────────────────────────────────────────────
# ④ 읽기 전용 — 쓰는 것은 원격 추적 ref뿐
# ─────────────────────────────────────────────────────────────────────────


def test_run_leaves_head_branches_worktree_and_index_untouched(repos: Repos):
    work = repos.work
    _git(work, "branch", "keep")
    (work / "README.md").write_text("다른 세션의 미커밋 수정\n", encoding="utf-8")
    (work / "scratch.txt").write_text("추적 안 되는 파일\n", encoding="utf-8")
    # 내용은 같고 시각만 바뀐 추적 파일 — 보통의 `git status`는 여기서 index를 다시 쓴다.
    later = time.time() + 30
    os.utime(work / "a.txt", (later, later))
    repos.advance_main()

    def state() -> tuple:
        return (
            _git(work, "rev-parse", "HEAD"),
            _git(work, "for-each-ref", "refs/heads"),
            _git(work, "--no-optional-locks", "status", "--porcelain"),
            (work / ".git" / "index").read_bytes(),
            (work / "README.md").read_bytes(),
            (work / "scratch.txt").read_bytes(),
        )

    before = state()
    trunk_before = _git(work, "rev-parse", "refs/remotes/origin/main")
    r = _cli(work, *LOCAL_ONLY)
    assert r.returncode == 1, r.stdout + r.stderr  # main 체크아웃이 1커밋 뒤처짐
    assert state() == before, "감시기가 HEAD·로컬 브랜치·작업 트리·index 중 하나를 바꿨다"
    # 아무것도 안 해서 통과한 것이 아님을 확인한다 — fetch는 실제로 원격 추적 ref를 옮겼다
    assert _git(work, "rev-parse", "refs/remotes/origin/main") != trunk_before
    assert "[정상] 작업 트리: 변경 1파일 · 추적 안 됨 1파일" in r.stdout


# ─────────────────────────────────────────────────────────────────────────
# 미머지 축 — 이 PC에만 있는 커밋
# ─────────────────────────────────────────────────────────────────────────


class TestLocalOnlyCommits:
    def test_unpushed_commit_is_attention_until_pushed(self, repos: Repos):
        _git(repos.work, "switch", "-q", "-c", "feat")
        _git(repos.work, "commit", "-q", "--allow-empty", "-m", "로컬 작업")
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "feat에 원격 어디에도 없는 커밋 1개" in r.stdout
        assert "git push -u origin feat" in r.stdout

        _git(repos.work, "push", "-q", "-u", "origin", "feat")
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[정상] 이 PC에만 있는 커밋(현재 브랜치): 없음" in r.stdout

    def test_commit_ahead_of_upstream_is_attention(self, repos: Repos):
        _git(repos.work, "switch", "-q", "-c", "feat")
        _git(repos.work, "push", "-q", "-u", "origin", "feat")
        _git(repos.work, "commit", "-q", "--allow-empty", "-m", "아직 안 올림")
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "feat에 원격 어디에도 없는 커밋 1개" in r.stdout

    def test_branch_tracking_main_but_pushed_to_its_own_branch_is_not_unpushed(self, repos: Repos):
        """upstream이 origin/main이면 `[ahead N]`은 main 대비 커밋 수다 — 미푸시가 아니다.

        `origin/main`에서 딴 브랜치를 `-u` 없이 push하면 upstream이 계속 origin/main이라,
        앞섬으로 세면 이미 `origin/feat`에 올라간 커밋을 '이 PC에만 있다'로 오경보한다.
        """
        _git(repos.work, "switch", "-q", "-c", "feat", "--track", "origin/main")
        _git(repos.work, "commit", "-q", "--allow-empty", "-m", "원격 브랜치에는 올림")
        _git(repos.work, "push", "-q", "origin", "feat")
        # 픽스처가 이 절을 실제로 밟는가 — upstream이 정말 origin/main이고 앞섬이 1이다
        assert _git(repos.work, "rev-parse", "--abbrev-ref", "feat@{upstream}") == "origin/main"
        assert _git(repos.work, "rev-list", "--count", "origin/main..feat") == "1"
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[정상] 이 PC에만 있는 커밋(현재 브랜치): 없음" in r.stdout

    def test_other_never_pushed_branch_is_attention(self, repos: Repos):
        _git(repos.work, "switch", "-q", "-c", "side")
        _git(repos.work, "commit", "-q", "--allow-empty", "-m", "옆 작업")
        _git(repos.work, "switch", "-q", "main")
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[주의] 이 PC에만 있는 커밋(다른 로컬 브랜치): 1개 브랜치 — side(1)" in r.stdout

    def test_branch_whose_remote_was_deleted_is_a_cleanup_candidate_not_unpushed(
        self, repos: Repos
    ):
        """스쿼시 머지 후 지워진 브랜치의 커밋은 main의 조상이 아니다 — 미푸시로 세면 오경보."""
        _git(repos.work, "switch", "-q", "-c", "merged-feature")
        _git(repos.work, "commit", "-q", "--allow-empty", "-m", "머지된 작업")
        _git(repos.work, "push", "-q", "-u", "origin", "merged-feature")
        _git(repos.work, "switch", "-q", "main")
        _git(repos.pusher, "push", "-q", "origin", "--delete", "merged-feature")
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "원격이 지워진 로컬 브랜치 1개" in r.stdout
        assert "[정리 후보] merged-feature" in r.stdout

    def test_standing_on_a_deleted_remote_branch_is_attention(self, repos: Repos):
        _git(repos.work, "switch", "-q", "-c", "merged-feature")
        _git(repos.work, "commit", "-q", "--allow-empty", "-m", "머지된 작업")
        _git(repos.work, "push", "-q", "-u", "origin", "merged-feature")
        _git(repos.pusher, "push", "-q", "origin", "--delete", "merged-feature")
        r = _cli(repos.work, *LOCAL_ONLY)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "원격에서 지워진 브랜치 위에 있다" in r.stdout
        assert "git switch main" in r.stdout


# ─────────────────────────────────────────────────────────────────────────
# 미머지 축 — 오래 머지 안 된 원격 브랜치 (HARN-47 스캔 위임)
# ─────────────────────────────────────────────────────────────────────────


class TestRemoteBranchAxis:
    def test_isolated_remote_branch_is_attention_and_clears_when_deleted(self, repos: Repos):
        _git(repos.pusher, "switch", "-q", "-c", "lonely")
        _git(repos.pusher, "commit", "-q", "--allow-empty", "-m", "PR 없는 작업")
        _git(repos.pusher, "push", "-q", "origin", "lonely")
        r = _cli(repos.work, "--skip", "prs", "--stale-days", "0")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[주의] 오래 머지 안 된 원격 브랜치(0일 이상): 고립 1" in r.stdout
        assert "[고립] lonely" in r.stdout

        _git(repos.pusher, "push", "-q", "origin", "--delete", "lonely")
        r = _cli(repos.work, "--skip", "prs", "--stale-days", "0")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[정상] 오래 머지 안 된 원격 브랜치(0일 이상): 고립 0" in r.stdout

    def test_shallow_clone_makes_the_branch_axis_unmeasured(self, repos: Repos, tmp_path: Path):
        shallow = tmp_path / "shallow"
        _git(tmp_path, "clone", "-q", "--depth", "1", f"file://{repos.bare}", str(shallow))
        assert _git(shallow, "rev-parse", "--is-shallow-repository") == "true"
        r = _cli(shallow, "--skip", "prs")
        assert r.returncode == 2, r.stdout + r.stderr
        # 사유는 **그 판정 줄**에 있어야 한다 — "shallow"는 보고서 머리글에도 나오므로
        # 문서 전체에서 찾으면 가드를 지워도 통과한다(2026-09-26 뮤테이션 M24 생존으로 발각).
        assert "[미측정] 오래 머지 안 된 원격 브랜치(3일 이상): shallow:" in r.stdout


# ─────────────────────────────────────────────────────────────────────────
# 미머지 축 — 열린 PR (HARN-30 분류 위임 · 가짜 GitHub)
# ─────────────────────────────────────────────────────────────────────────

_RULES = [
    {
        "type": "required_status_checks",
        "parameters": {"required_status_checks": [{"context": "policy-guard"}]},
    }
]


def _pr(number: int, sha: str, state: str = "clean") -> dict:
    return {
        "number": number,
        "title": f"PR {number}",
        "head": {"sha": sha, "ref": f"branch-{number}"},
        "draft": False,
        "mergeable_state": state,
    }


def _run(name: str, conclusion: str | None) -> dict:
    status = "completed" if conclusion else "in_progress"
    return {"name": name, "status": status, "conclusion": conclusion}


class _FakeGitHub:
    def __init__(self, routes: dict[str, tuple[int, object]]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def get(self, path: str) -> tuple[int, object]:
        self.calls.append(path)
        for prefix, response in self.routes.items():
            if path.startswith(prefix):
                return response
        raise SystemExit(f"❌ 측정 실패 — 가짜 경로 없음: {path}")


def _install(monkeypatch, routes: dict[str, tuple[int, object]]) -> _FakeGitHub:
    fake = _FakeGitHub(routes)
    monkeypatch.setattr(mw.pda, "_get", fake.get)
    monkeypatch.setattr(mw.pda, "_merge_state", lambda repo, pr: (pr["mergeable_state"], 0))
    return fake


_TOKEN = mw.Options(repo_slug="o/r", token_source="GITHUB_TOKEN")


class TestPrAxis:
    def test_classifies_with_harn30_and_flags_only_attention_states(self, repos, monkeypatch):
        _install(
            monkeypatch,
            {
                "/repos/o/r/rules/branches/main": (200, _RULES),
                "/repos/o/r/pulls": (200, [_pr(1, "s1"), _pr(2, "s2"), _pr(3, "s3")]),
                "/repos/o/r/commits/s1/": (200, {"check_runs": []}),
                "/repos/o/r/commits/s2/": (200, {"check_runs": [_run("policy-guard", "success")]}),
                "/repos/o/r/commits/s3/": (200, {"check_runs": [_run("policy-guard", None)]}),
            },
        )
        axis = mw.measure_prs(repos.work, _TOKEN, trunk_branch="main", trunk_sha=None, prev=None)
        assert axis.status == "ok"
        assert {e.number: e.state for e in axis.entries} == {
            1: "NO_CHECKS",
            2: "READY_UNMERGED",
            3: "REQUIRED_PENDING",
        }
        sig = mw._pr_signal(axis)
        assert sig.state == mw.ATTENTION
        assert sig.detail.startswith("3건 중 주의 2건")  # 진행 중(REQUIRED_PENDING)은 주의가 아니다

    def test_unreadable_check_runs_are_unmeasured_not_no_checks(self, repos, monkeypatch):
        """체크런을 못 읽은 것을 '체크런 0건'(NO_CHECKS)으로 접으면 틀린 처방이 나간다."""
        _install(
            monkeypatch,
            {
                "/repos/o/r/rules/branches/main": (200, _RULES),
                "/repos/o/r/pulls": (200, [_pr(1, "s1")]),
                "/repos/o/r/commits/s1/": (403, {"message": "API rate limit exceeded"}),
            },
        )
        axis = mw.measure_prs(repos.work, _TOKEN, trunk_branch="main", trunk_sha=None, prev=None)
        assert axis.status == "failed"
        assert "PR #1 체크런 조회 실패(HTTP 403)" in axis.error
        assert mw._pr_signal(axis).state == mw.UNMEASURED

    def test_without_token_lists_only_and_says_ci_is_unmeasured(self, repos, monkeypatch):
        fake = _install(monkeypatch, {"/repos/o/r/pulls": (200, [_pr(7, "s7")])})
        opts = mw.Options(repo_slug="o/r", token_source="")
        axis = mw.measure_prs(repos.work, opts, trunk_branch="main", trunk_sha=None, prev=None)
        assert axis.status == "list_only"
        assert [e.state for e in axis.entries] == [None]
        assert fake.calls == ["/repos/o/r/pulls?state=open&per_page=100"]  # 분류용 호출 0
        sig = mw._pr_signal(axis)
        assert sig.state == mw.UNMEASURED
        assert "CI·머지 상태는 못 쟀다" in sig.detail

    def test_api_failure_is_kept_as_unmeasured_with_its_cause(self, repos, monkeypatch):
        _install(monkeypatch, {})  # 모든 경로가 SystemExit(측정 실패)
        axis = mw.measure_prs(repos.work, _TOKEN, trunk_branch="main", trunk_sha=None, prev=None)
        assert axis.status == "failed"
        assert "가짜 경로 없음" in axis.error  # 원인 문구가 보존된다
        assert mw._pr_signal(axis).state == mw.UNMEASURED

    def test_repo_slug_is_read_from_origin(self, repos: Repos):
        for url, slug in (
            ("https://github.com/kiki-s-broom/WhyMath", "kiki-s-broom/WhyMath"),
            ("git@github.com:o/r.git", "o/r"),
            ("https://x-access-token:abc@github.com/o/r.git", "o/r"),
            (str(repos.bare), ""),
        ):
            _git(repos.work, "remote", "set-url", "origin", url)
            assert mw.repo_slug_from_origin(repos.work) == slug, url


def _snapshot(**parts) -> mw.Snapshot:
    return mw.Snapshot(
        taken_at="t",
        repo_root="r",
        code_root="r",
        repo_slug="",
        token_note="",
        local=parts.get("local", _facts()),
        prs=parts.get("prs", mw.PrAxis()),
        branches=parts.get("branches", mw.BranchAxis()),
        signals=parts.get("signals", []),
    )


def _entry(number: int, state: str | None) -> mw.PrEntry:
    return mw.PrEntry(number, f"PR {number}", f"b{number}", False, state)


class TestPrEvents:
    def test_opened_merged_disappeared_and_transition(self):
        prev = _snapshot(
            prs=mw.PrAxis(
                status="ok",
                measured_at="t1",
                entries=[
                    _entry(1, "READY_UNMERGED"),
                    _entry(2, "REQUIRED_PENDING"),
                    _entry(3, "CONFLICT"),
                ],
            )
        )
        cur = _snapshot(
            prs=mw.PrAxis(
                status="ok",
                measured_at="t2",
                entries=[_entry(2, "READY_UNMERGED"), _entry(4, "NO_CHECKS")],
                landed={1: "abc1234"},
            )
        )
        texts = [e.text for e in mw.diff_events(prev, cur)]
        assert any(t.startswith("새 PR #4") for t in texts)
        assert any(t.startswith("PR #1 머지됨") and "abc1234" in t for t in texts)
        assert any(t.startswith("PR #3 목록에서 사라짐") for t in texts)
        assert any(t.startswith("PR #2 상태: REQUIRED_PENDING → READY_UNMERGED") for t in texts)

    def test_no_events_when_the_pr_axis_was_not_remeasured(self):
        axis = mw.PrAxis(status="ok", measured_at="t1", entries=[_entry(1, "CONFLICT")])
        later = mw.PrAxis(status="ok", measured_at="t1", entries=[])
        assert mw.diff_events(_snapshot(prs=axis), _snapshot(prs=later)) == []

    def test_no_disappearance_claim_when_one_side_was_unmeasured(self):
        before = mw.PrAxis(status="failed", measured_at="t1", error="x")
        after = mw.PrAxis(status="ok", measured_at="t2", entries=[_entry(1, "CONFLICT")])
        assert mw.diff_events(_snapshot(prs=before), _snapshot(prs=after)) == []
        assert mw.diff_events(_snapshot(prs=after), _snapshot(prs=before)) == []


def test_landed_pr_numbers_read_the_squash_suffix(repos: Repos):
    old = _git(repos.work, "rev-parse", "HEAD")
    new = repos.advance_main("feat: 가 (#10)", "chore: 번호 없음", "fix: 나 (#11)")
    _git(repos.work, "fetch", "-q", "origin")
    landed = mw.landed_pr_numbers(repos.work, old, new)
    assert set(landed) == {10, 11}
    assert mw.landed_pr_numbers(repos.work, new, new) == {}


# ─────────────────────────────────────────────────────────────────────────
# ⑤ Windows — cp949로 리다이렉트된 표준출력에서도 죽지 않는다
# ─────────────────────────────────────────────────────────────────────────


def test_cp949_redirected_stdout_does_not_crash(repos: Repos):
    repos.advance_main("🚀 배포 ⚠ 완료")  # cp949로 표현할 수 없는 글자 2개
    _git(repos.work, "pull", "-q", "--ff-only")
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    env.update({"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp949"})
    r = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(repos.work), "--no-gh", *LOCAL_ONLY],
        capture_output=True,
        env=env,
        timeout=180,
    )
    stderr = r.stderr.decode("utf-8", "replace")
    assert "UnicodeEncodeError" not in stderr, stderr
    assert r.returncode == 0, stderr
    text = r.stdout.decode("cp949")
    assert "[판정]" in text
    assert "? 배포 ? 완료" in text  # 표현 못 한 글자는 '?'로 — 줄은 살아남는다


def test_json_output_is_ascii_and_carries_the_exit_code(repos: Repos):
    r = _cli(repos.work, "--json", *LOCAL_ONLY)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.isascii()
    data = json.loads(r.stdout)
    assert data["exit_code"] == 0
    assert {s["key"] for s in data["signals"]} >= {"fetch", "trunk", "head", "worktree"}


# ─────────────────────────────────────────────────────────────────────────
# CLI 계약 · 토큰 취급
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "args",
    [("--watch", "--json"), ("--interval", "5"), ("--slow-interval", "30")],
    ids=["watch-with-json", "interval-too-short", "slow-interval-too-short"],
)
def test_usage_errors_exit_3_not_2(repos: Repos, args):
    """argparse 기본 종료 코드 2는 이 도구에서 '측정 실패'다 — 사용 오류와 섞지 않는다."""
    r = _cli(repos.work, *args)
    assert r.returncode == 3, r.stdout + r.stderr


def test_not_a_git_repository_exits_3(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    r = _cli(plain, *LOCAL_ONLY)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "git 저장소를 찾지 못했다" in r.stderr


class TestToken:
    def test_env_token_reports_the_source_never_the_value(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "secret-value-xyz")
        source, note = mw.resolve_token(use_gh=True)
        assert source == "GITHUB_TOKEN"
        assert "secret-value-xyz" not in note

    def test_no_token_without_gh_is_said_out_loud(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        assert mw.resolve_token(use_gh=False) == ("", "토큰 없음(--no-gh)")

    @pytest.mark.skipif(sys.platform == "win32", reason="가짜 gh는 sh 스크립트다")
    def test_gh_token_is_borrowed_into_this_process_only(self, monkeypatch, tmp_path: Path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text("#!/bin/sh\necho gho_fake_token_123\n", encoding="utf-8")
        gh.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "placeholder")  # 끝나면 원래 상태로 되돌리게 기록
        monkeypatch.delenv("GH_TOKEN")
        source, note = mw.resolve_token(use_gh=True)
        assert source == "gh"
        assert os.environ["GH_TOKEN"] == "gho_fake_token_123"
        assert "gho_fake_token_123" not in note

    @pytest.mark.skipif(sys.platform == "win32", reason="가짜 gh는 sh 스크립트다")
    def test_logged_out_gh_is_reported_not_silent(self, monkeypatch, tmp_path: Path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text("#!/bin/sh\necho 'not logged in' >&2\nexit 1\n", encoding="utf-8")
        gh.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        source, note = mw.resolve_token(use_gh=True)
        assert source == ""
        assert "gh auth login 필요" in note
