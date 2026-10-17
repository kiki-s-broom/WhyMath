"""판정 입력 규칙의 계약 동결 — HARN-172 (ci_job_coverage scope·check · ci_mirror 자동 선택).

사고(2026-09-25 PR #1305 · series ci-local-repro-gap 3회차): 변경을 staged만 한 상태로
`git diff --cached --name-only | ci_job_coverage.py scope`를 돌렸다. scope는 stdin을 읽지 않고
기본 `--diff-base origin/main`으로 **커밋된** diff(0건)를 계산해 "변경 파일 0건"·exit 0으로
상시 잡만 내놓았고, 세션은 출력을 `tail -15`로 잘라 머리말의 0건을 보지 못했다.

이 파일이 지키는 것 (acceptance ⑤ — 픽스처 3종 + 대조군 + 가드별 뮤테이션):
  ① 0건 입력 → exit 2 + 사유 · `--allow-empty`만이 통과 경로
  ② 파이프 입력(`--stdin` 없음) → exit 2 거부 · `--stdin`이면 명시 소비 · 열린 빈 파이프는
     거부하지도 멈추지도 않는다 · 감지는 stdin을 소비하지 않는다
  ③ 머리말에 사용한 파일 목록 *전체* · 미커밋만 있는 트리 → 0건 사유에 미커밋 건수 ·
     커밋+미커밋 트리 → 경고(머리말 + 마지막 줄 — tail로 잘라 읽어도 보이게)
  ④ ci_mirror run 자동 선택이 같은 규칙을 따른다 — 그리고 변경 있는 브랜치의 정상 흐름은 그대로다

CLI 동작은 **실제 git 저장소를 만든 서브프로세스**로 본다. 파이프·stdin·미커밋 상태는
in-process로 흉내 내면 그 절을 밟지 않는다(CLAUDE.md 2026-09-07 픽스처 접촉 규칙). 계약
단언은 함수로 두고, 뮤테이션 테스트가 **같은 함수**를 변이 사본에 대 RED를 확인한다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COVERAGE_PATH = _REPO_ROOT / "scripts" / "harness" / "ci_job_coverage.py"
_MIRROR_PATH = _REPO_ROOT / "scripts" / "harness" / "ci_mirror.py"

_POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX 파이프·pty 전용 픽스처")


def _load(path: Path, name: str):
    """스크립트를 모듈로 로드한다. dataclass가 sys.modules를 조회하므로 exec 전에 등록한다."""
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"로드 실패: {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


coverage = _load(_COVERAGE_PATH, "ci_job_coverage_harn172")


# ── 픽스처: 실제 git 저장소 ────────────────────────────────────────────────
#: 전역 git 설정(서명 강제 등)이 픽스처 커밋을 막지 않게 격리한다. 도구 서브프로세스도 같은
#: 환경을 물려받아 같은 저장소 상태를 본다.
_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

#: 최소 워크플로 — `changes` 잡의 path filter(정본 형태 그대로)·필터 잡·상시 잡 하나씩.
_WORKFLOW = """\
name: ci
on: [pull_request]
jobs:
  changes:
    runs-on: ubuntu-latest
    steps:
      - id: filter
        run: |
          be=false
          if printf '%s\\n' "$files" | grep -qE '^(src/backend/)'; then
            be=true
          fi
          echo "backend=$be" >> "$GITHUB_OUTPUT"
  backend:
    needs: changes
    if: needs.changes.outputs.backend == 'true'
    steps:
      - name: backend ok
        run: echo backend-ran
  always:
    steps:
      - name: always ok
        run: echo always-ran
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, env=_GIT_ENV, check=True, capture_output=True, timeout=60
    )


def _write(repo: Path, rel: str, text: str = "x\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, *rels: str, message: str = "change") -> None:
    for rel in rels:
        _write(repo, rel)
    _git(repo, "add", "--", *rels)
    _git(repo, "commit", "-q", "-m", message)


def _fresh_repo(parent: Path) -> Path:
    """`base` 브랜치 = 기준. 그 위에 변경을 얹어 diff-base 판정을 실제로 계산하게 한다.

    뮤테이션·대조마다 독립 저장소를 만든다 — 앞 단언이 남긴 커밋이 뒤 단언의 전제를 바꾸지 않게.
    """
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root, ".github/workflows/ci.yml", _WORKFLOW)
    _write(root, "README.md", "readme\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "branch", "base")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _fresh_repo(tmp_path)


def _toolset(tmp_path: Path, coverage_src: str | None = None, mirror_src: str | None = None):
    """두 도구를 한 디렉터리에 둔다 — ci_mirror는 같은 디렉터리의 ci_job_coverage를 임포트한다."""
    tools = tmp_path / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    cov = tools / "ci_job_coverage.py"
    mir = tools / "ci_mirror.py"
    cov.write_text(coverage_src or _COVERAGE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    mir.write_text(mirror_src or _MIRROR_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    # 두 도구의 `__main__` 블록이 같은 디렉터리의 _stdio를 임포트한다(OPS-53)
    stdio = _MIRROR_PATH.parent / "_stdio.py"
    (tools / "_stdio.py").write_text(stdio.read_text(encoding="utf-8"), encoding="utf-8")
    return cov, mir


def _scope(tool: Path, repo: Path, *args: str, stdin_bytes: bytes | None = None):
    """scope를 서브프로세스로 돌린다. stdin을 명시하지 않으면 /dev/null(부모 stdin에 비의존)."""
    cmd = [
        sys.executable,
        str(tool),
        "--workflow",
        str(repo / ".github" / "workflows" / "ci.yml"),
        "scope",
        "--diff-base",
        "base",
        *args,
    ]
    kwargs: dict = {"cwd": repo, "env": _GIT_ENV, "capture_output": True, "timeout": 60}
    if stdin_bytes is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin_bytes
    proc = subprocess.run(cmd, **kwargs)
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
    )


def _mirror(tool: Path, repo: Path, *args: str, stdin_bytes: bytes | None = None):
    """ci_mirror run을 서브프로세스로 돌린다(cwd = 픽스처 저장소 = 미러의 repo_root)."""
    cmd = [
        sys.executable,
        str(tool),
        "--workflow",
        str(repo / ".github" / "workflows" / "ci.yml"),
        "--result",
        str(repo.parent / "mirror_result.json"),
        "run",
        "--diff-base",
        "base",
        *args,
    ]
    kwargs: dict = {"cwd": repo, "env": _GIT_ENV, "capture_output": True, "timeout": 120}
    if stdin_bytes is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin_bytes
    proc = subprocess.run(cmd, **kwargs)
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
    )


def _to_cover_line(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.startswith("로컬이 봐야 하는 잡:")]
    assert len(lines) == 1, f"판정 줄이 1개가 아니다:\n{out}"
    return lines[0]


def _last_line(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines, "출력이 비었다"
    return lines[-1]


def _header(out: str) -> list[str]:
    """첫 빈 줄까지 = 머리말(잡 그룹 앞)."""
    head: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            break
        head.append(line)
    return head


# ── 계약 단언 (뮤테이션 테스트가 같은 함수를 변이 사본에 댄다) ─────────────
def _assert_zero_input_exits_2(tool: Path, repo: Path) -> None:
    """① 0건 픽스처 — 기준 이후 커밋·미커밋 변경이 전혀 없는 트리."""
    rc, out, err = _scope(tool, repo)
    assert rc == 2, f"변경 0건인데 exit {rc} — 스캔 0건을 통과로 접었다\n{out}{err}"
    assert "판정 대상 없음" in err and "--allow-empty" in err, err
    assert "--diff-base" in err and "--changed-file" in err, "원인 후보 두 가지를 말하지 않는다"
    assert "로컬이 봐야 하는 잡" not in out, "거부했다면서 판정을 냈다 — 사람은 판정 줄을 읽는다"


def _assert_allow_empty_passes(tool: Path, repo: Path) -> None:
    """① 대조 — 의도한 0건은 `--allow-empty`로 통과하고, 0건이라는 사실을 머리말에 적는다."""
    rc, out, err = _scope(tool, repo, "--allow-empty")
    assert rc == 0, f"--allow-empty인데 exit {rc}\n{out}{err}"
    assert "사용한 변경 파일 0건" in out, out
    assert "always" in _to_cover_line(out) and "backend" not in _to_cover_line(out)


def _assert_piped_list_is_rejected(tool: Path, repo: Path) -> None:
    """② 파이프 픽스처 — 커밋된 변경이 있어 diff-base로 새면 exit 0이 되는 트리에서 거부한다."""
    _commit(repo, "docs/committed.md")
    rc, out, err = _scope(tool, repo, stdin_bytes=b"src/backend/staged.py\n")
    assert rc == 2, (
        f"파이프로 목록을 넘겼는데 exit {rc} — stdin을 조용히 버리고 diff-base로 판정했다\n"
        f"{out}{err}"
    )
    assert "--stdin" in err, "무엇을 하면 되는지(--stdin) 말하지 않는다"
    assert "로컬이 봐야 하는 잡" not in out


def _assert_stdin_flag_consumes(tool: Path, repo: Path) -> None:
    """② 대조 — `--stdin`이면 파이프 목록이 판정 입력이 되고 출처가 머리말에 남는다."""
    _commit(repo, "docs/committed.md")
    rc, out, err = _scope(tool, repo, "--stdin", stdin_bytes=b"src/backend/staged.py\r\n\n")
    assert rc == 0, f"--stdin 판정이 exit {rc}\n{out}{err}"
    assert "출처: --stdin" in out and "  - src/backend/staged.py" in out, out
    assert "backend" in _to_cover_line(out), "파이프 목록으로 판정하지 않았다"
    assert "docs/committed.md" not in out, "--stdin인데 diff-base 목록이 섞였다"


def _assert_full_file_list_in_header(tool: Path, repo: Path) -> None:
    """③ 머리말에 사용 목록 **전체** — 15건을 하나도 자르지 않는다."""
    rels = [f"docs/f{i:02d}.md" for i in range(15)]
    _commit(repo, *rels)
    rc, out, err = _scope(tool, repo)
    assert rc == 0, f"{out}{err}"
    head = _header(out)
    assert any("사용한 변경 파일 15건" in ln for ln in head), head
    listed = [ln for ln in head if ln.startswith("  - ")]
    assert listed == [f"  - {r}" for r in rels], f"사용 목록이 전체가 아니다: {listed}"


def _assert_uncommitted_only_tree(tool: Path, repo: Path) -> None:
    """③ 미커밋만 있는 트리 픽스처 — 사고 그 형태. 0건 거부 사유에 빠진 미커밋 건수를 적는다."""
    _write(repo, "src/backend/staged.py")
    _git(repo, "add", "--", "src/backend/staged.py")
    _write(repo, "README.md", "changed\n")  # unstaged
    _write(repo, "docs/untracked.md")  # untracked
    rc, out, err = _scope(tool, repo)
    assert rc == 2, f"미커밋 변경만 있는데 exit {rc} — 사고 재생산\n{out}{err}"
    assert "미커밋 변경 3건" in err, err
    assert "staged 1 · unstaged 1 · untracked 1" in err, err
    assert "src/backend/staged.py" in err, "빠진 경로를 이름으로 지목하지 않는다"


def _assert_uncommitted_warning(tool: Path, repo: Path) -> None:
    """③ 커밋 + 미커밋 트리 — 판정은 내되, 빠진 미커밋 건수를 머리말과 **마지막 줄**에 낸다.

    `docs/committed.md`는 커밋된 뒤 더 고쳤으므로(unstaged) 경로가 이미 판정 목록에 있다 —
    빠진 것으로 세면 과잉 경고다. 빠진 것은 untracked 1건뿐이다.
    """
    _commit(repo, "docs/committed.md")
    _write(repo, "docs/committed.md", "more\n")
    _write(repo, "src/backend/new_module.py")
    rc, out, err = _scope(tool, repo)
    assert rc == 0, f"{out}{err}"
    head = _header(out)
    assert any(ln.startswith("⚠ 미커밋 변경 1건") for ln in head), f"머리말 경고 없음: {head}"
    assert _last_line(out).startswith(
        "⚠ 미커밋 변경 1건"
    ), f"마지막 줄에 경고가 없다 — tail로 자르면 안 보인다: {_last_line(out)!r}"
    assert "src/backend/new_module.py" in out
    assert "backend" not in _to_cover_line(out), "픽스처 전제(미커밋은 판정 밖) 붕괴"


def _assert_clean_committed_change_is_quiet(tool: Path, repo: Path) -> None:
    """대조군 — 커밋된 변경만 있는 깨끗한 트리는 exit 0 · 경고 0줄 · 판정 줄이 마지막이다."""
    _commit(repo, "src/backend/committed.py")
    rc, out, err = _scope(tool, repo)
    assert rc == 0, f"{out}{err}"
    assert "⚠" not in out and "⚠" not in err, "경고할 것이 없는데 경고했다 — 상시 경고는 소음"
    assert _last_line(out).startswith("로컬이 봐야 하는 잡:")
    assert "backend" in _to_cover_line(out)


def _assert_mirror_zero_exits_2(tool: Path, repo: Path) -> None:
    """④ 미러 자동 선택의 0건 — 상시 잡만 돌려 '✔ 전 잡 통과'를 내지 않고 exit 2로 멈춘다."""
    rc, out, err = _mirror(tool, repo)
    assert rc == 2, f"미러가 변경 0건에서 exit {rc} — 상시 잡만 돌리고 통과로 보고했다\n{out}{err}"
    assert "판정 대상 없음" in err, err
    assert not (repo.parent / "mirror_result.json").exists(), "거부했다면서 결과를 남겼다"


def _assert_mirror_pipe_rejected(tool: Path, repo: Path) -> None:
    """④ 미러 자동 선택의 파이프 입력 — `--stdin` 없이는 거부, 있으면 그 목록으로 잡을 고른다."""
    _commit(repo, "docs/committed.md")
    rc, out, err = _mirror(tool, repo, stdin_bytes=b"src/backend/staged.py\n")
    assert rc == 2 and "--stdin" in err, f"미러가 파이프 목록을 조용히 버렸다(exit {rc})\n{out}"
    rc, out, err = _mirror(tool, repo, "--stdin", stdin_bytes=b"src/backend/staged.py\n")
    assert rc == 0, f"{out}{err}"
    assert "── backend (exit 0)" in out, "파이프 목록으로 backend 잡을 고르지 않았다"


def _assert_mirror_uncommitted_tail(tool: Path, repo: Path) -> None:
    """④ 미러도 미커밋 누락을 머리말과 최종 줄 뒤에 낸다(결과를 tail로 읽는 흐름)."""
    _commit(repo, "docs/committed.md")
    _write(repo, "src/backend/new_module.py")
    rc, out, err = _mirror(tool, repo)
    assert rc == 0, f"{out}{err}"
    assert "── backend" not in out, "픽스처 전제(미커밋은 판정 밖) 붕괴"
    assert _last_line(out).startswith("⚠ 미커밋 변경 1건"), _last_line(out)


def _assert_mirror_normal_flow(tool: Path, repo: Path) -> None:
    """④ 정상 흐름 — 변경이 커밋된 브랜치의 `run --diff-base <기준>`은 그대로 돈다."""
    _commit(repo, "src/backend/committed.py")
    rc, out, err = _mirror(tool, repo)
    assert rc == 0, f"정상 흐름이 깨졌다(exit {rc})\n{out}{err}"
    assert "사용한 변경 파일 1건" in out and "  - src/backend/committed.py" in out
    assert "── backend (exit 0)" in out and "── always (exit 0)" in out
    assert _last_line(out) == "✔ 전 잡 통과", _last_line(out)


class _FakeTtyStream:
    """isatty가 참인 입력 — 가드가 없으면 read()가 데이터를 돌려줘 **멈추지 않고** RED가 된다."""

    def isatty(self) -> bool:
        return True

    def read(self) -> str:
        return "src/backend/typed.py\n"


def _assert_stdin_tty_is_rejected(module) -> None:
    # pytest.raises의 "DID NOT RAISE"는 AssertionError가 아니라(BaseException 계열) 뮤테이션
    # 테스트가 RED로 셀 수 없다 — 계약 단언은 AssertionError로만 실패하게 쓴다.
    try:
        paths = module.read_stdin_paths(_FakeTtyStream())
    except module.InputRejectedError as exc:
        assert "터미널" in str(exc), str(exc)
        return
    raise AssertionError(
        f"터미널 stdin을 --stdin으로 읽었다 — 사람 입력을 기다리며 멈춘다: {paths}"
    )


def _assert_non_utf8_is_rejected(module) -> None:
    class _Bytes:
        buffer = io.BytesIO(b"src/backend/\xff\xfe.py\n")

        def isatty(self) -> bool:
            return False

    try:
        paths = module.read_stdin_paths(_Bytes())
    except module.InputRejectedError as exc:
        assert "UTF-8" in str(exc), str(exc)
        return
    raise AssertionError(f"UTF-8이 아닌 입력을 깨진 경로로 받아들였다: {paths}")


def _assert_poll_pipe_logic(module) -> None:
    """Windows 경로의 판정(PeekNamedPipe 결과 → 있음/없음/모름)을 가짜 조회로 본다."""
    clock = [0.0]

    def tick(seconds: float) -> None:
        clock[0] += seconds

    def seq(*answers):
        items = list(answers)
        return lambda: items.pop(0) if len(items) > 1 else items[0]

    def now() -> float:
        return clock[0]

    assert module._poll_pipe(seq((0, False), (0, False), (5, False)), 0.5, now, tick) is True
    assert module._poll_pipe(seq((0, True)), 0.5, now, tick) is False
    assert module._poll_pipe(seq((None, False)), 0.5, now, tick) is None
    clock[0] = 0.0
    assert module._poll_pipe(seq((0, False)), 0.5, now, tick) is False
    assert clock[0] >= 0.5, "유예를 다 기다리지 않고 '없음'이라 했다"


# ── ① 0건 ─────────────────────────────────────────────────────────────────
class TestZeroInput:
    def test_zero_changed_files_exits_2(self, repo):
        _assert_zero_input_exits_2(_COVERAGE_PATH, repo)

    def test_allow_empty_is_the_only_pass(self, repo):
        _assert_allow_empty_passes(_COVERAGE_PATH, repo)

    def test_blank_changed_file_counts_as_zero(self, repo):
        """`--changed-file ""`처럼 빈 값만 준 명시 입력도 0건이다 — 빈 경로로 판정하지 않는다."""
        rc, _out, err = _scope(_COVERAGE_PATH, repo, "--changed-file", "  ")
        assert rc == 2 and "판정 대상 없음" in err

    def test_check_subcommand_shares_the_rule(self, repo):
        """check도 같은 창구를 쓴다 — 0건으로 '커버리지 충족'을 내면 같은 사고다."""
        cmd = [
            sys.executable,
            str(_COVERAGE_PATH),
            "--workflow",
            str(repo / ".github" / "workflows" / "ci.yml"),
            "check",
            "--diff-base",
            "base",
            "--ran",
            "always",
        ]
        proc = subprocess.run(
            cmd, cwd=repo, env=_GIT_ENV, stdin=subprocess.DEVNULL, capture_output=True, timeout=60
        )
        assert proc.returncode == 2, proc.stdout.decode("utf-8", errors="replace")
        assert "판정 대상 없음" in proc.stderr.decode("utf-8", errors="replace")


# ── ② 파이프 입력 ─────────────────────────────────────────────────────────
class TestPipedInput:
    def test_piped_list_without_flag_is_rejected(self, repo):
        _assert_piped_list_is_rejected(_COVERAGE_PATH, repo)

    def test_stdin_flag_consumes_the_list(self, repo):
        _assert_stdin_flag_consumes(_COVERAGE_PATH, repo)

    def test_empty_stdin_with_flag_is_zero_input(self, repo):
        rc, _out, err = _scope(_COVERAGE_PATH, repo, "--stdin", stdin_bytes=b"")
        assert rc == 2 and "판정 대상 없음" in err

    def test_explicit_changed_file_is_not_second_guessed(self, repo):
        """acceptance ② 문면 — `--changed-file`이 있으면 파이프 감지를 하지 않는다
        (`while read` 루프 안의 호출처럼 stdin이 남의 것인 경우를 거짓 거부하지 않는다)."""
        rc, out, _err = _scope(
            _COVERAGE_PATH,
            repo,
            "--changed-file",
            "src/backend/x.py",
            stdin_bytes=b"other/line\n",
        )
        assert rc == 0 and "backend" in _to_cover_line(out)

    @_POSIX_ONLY
    def test_open_empty_pipe_is_neither_rejected_nor_blocking(self, repo, tmp_path):
        """열린 채 비어 있는 stdin(비대화형 하네스의 흔한 형태) — 거부도, 블로킹 read도 없다."""
        _commit(repo, "src/backend/committed.py")
        out_path = tmp_path / "out.txt"
        cmd = [
            sys.executable,
            str(_COVERAGE_PATH),
            "--workflow",
            str(repo / ".github" / "workflows" / "ci.yml"),
            "scope",
            "--diff-base",
            "base",
        ]
        started = time.monotonic()
        with out_path.open("wb") as sink:
            proc = subprocess.Popen(
                cmd, cwd=repo, env=_GIT_ENV, stdin=subprocess.PIPE, stdout=sink, stderr=sink
            )
            try:
                rc = proc.wait(timeout=30)  # stdin은 끝까지 열어 둔다 — 쓰는 쪽이 살아 있는 상태
            finally:
                assert proc.stdin is not None
                proc.stdin.close()
                if proc.poll() is None:
                    proc.kill()
        elapsed = time.monotonic() - started
        text = out_path.read_text(encoding="utf-8", errors="replace")
        assert rc == 0, f"열린 빈 파이프를 거부했다(exit {rc})\n{text}"
        assert elapsed < 20, f"{elapsed:.1f}s — 블로킹 read로 멈췄다"
        assert "backend" in _to_cover_line(text)

    def test_stdin_on_terminal_is_rejected(self):
        _assert_stdin_tty_is_rejected(coverage)

    @_POSIX_ONLY
    def test_real_pty_is_detected_as_terminal(self):
        """가짜 스트림만으로는 isatty 실물 판정을 밟지 않는다 — 실제 pty로 한 번 더 본다."""
        master, slave = os.openpty()
        try:
            with os.fdopen(slave, "rb", buffering=0, closefd=False) as stream:
                with pytest.raises(coverage.InputRejectedError, match="터미널"):
                    coverage.read_stdin_paths(stream)
                assert coverage.stdin_pending_data(stream) is False
        finally:
            os.close(master)
            os.close(slave)

    def test_non_utf8_stdin_is_rejected(self):
        _assert_non_utf8_is_rejected(coverage)


@_POSIX_ONLY
class TestStdinDetector:
    """감지기 자체 — 소비하지 않고(비소비) 멈추지 않는다(비차단)."""

    def test_pipe_with_data_is_detected_without_consuming(self):
        r, w = os.pipe()
        try:
            os.write(w, b"src/backend/a.py\n")
            with os.fdopen(r, "rb", buffering=0, closefd=False) as stream:
                assert coverage.stdin_pending_data(stream, grace=0.2) is True
                assert os.read(r, 100) == b"src/backend/a.py\n", "감지가 stdin을 갉아 먹었다"
        finally:
            os.close(r)
            os.close(w)

    def test_open_empty_pipe_is_no_data_within_grace(self):
        r, w = os.pipe()
        try:
            with os.fdopen(r, "rb", buffering=0, closefd=False) as stream:
                started = time.monotonic()
                assert coverage.stdin_pending_data(stream, grace=0.2) is False
                assert time.monotonic() - started < 5
        finally:
            os.close(r)
            os.close(w)

    def test_closed_empty_pipe_is_no_data(self):
        r, w = os.pipe()
        os.close(w)
        try:
            with os.fdopen(r, "rb", buffering=0, closefd=False) as stream:
                assert coverage.stdin_pending_data(stream, grace=5) is False
        finally:
            os.close(r)

    def test_regular_file_redirect(self, tmp_path):
        full = tmp_path / "list.txt"
        full.write_bytes(b"src/backend/a.py\n")
        empty = tmp_path / "empty.txt"
        empty.write_bytes(b"")
        with full.open("rb") as stream:
            assert coverage.stdin_pending_data(stream) is True
        with empty.open("rb") as stream:
            assert coverage.stdin_pending_data(stream) is False

    def test_dev_null_is_no_data(self):
        with open(os.devnull, "rb") as stream:
            assert coverage.stdin_pending_data(stream) is False

    def test_no_fileno_is_unknown_not_false(self):
        """pytest 캡처처럼 fileno가 없는 대체 객체 — '모른다'(None)이지 '없다'가 아니다."""
        assert coverage.stdin_pending_data(io.StringIO("x\n")) is None

    def test_windows_poll_logic(self):
        _assert_poll_pipe_logic(coverage)


# ── ③ 머리말·미커밋 ───────────────────────────────────────────────────────
class TestHeaderAndUncommitted:
    def test_full_file_list_in_header(self, repo):
        _assert_full_file_list_in_header(_COVERAGE_PATH, repo)

    def test_uncommitted_only_tree_exits_2_with_count(self, repo):
        _assert_uncommitted_only_tree(_COVERAGE_PATH, repo)

    def test_uncommitted_excluded_is_warned_top_and_bottom(self, repo):
        _assert_uncommitted_warning(_COVERAGE_PATH, repo)

    def test_clean_committed_change_is_quiet(self, repo):
        _assert_clean_committed_change_is_quiet(_COVERAGE_PATH, repo)

    def test_json_carries_input_fields(self, repo):
        _commit(repo, "docs/committed.md")
        _write(repo, "src/backend/new_module.py")
        rc, out, err = _scope(_COVERAGE_PATH, repo, "--json")
        assert rc == 0, err
        payload = json.loads(out)
        assert payload["changed_files"] == ["docs/committed.md"]
        assert payload["changed_files_source"] == "git diff --name-only base...HEAD"
        assert payload["uncommitted_excluded"] == ["src/backend/new_module.py"]
        assert payload["uncommitted_excluded_count"] == 1
        assert "미커밋 변경 1건" in err, "JSON 모드의 경고가 사라졌다(stderr)"

    def test_uncommitted_probe_failure_is_unknown_not_zero(self, monkeypatch, tmp_path):
        """미커밋 조회가 실패하면 '0건'이 아니라 '모른다'를 경고한다."""

        def boom(root):
            raise RuntimeError("git ls-files 실패(exit 128)")

        monkeypatch.setattr(coverage, "changed_files_from_git", lambda base, root: ["docs/x.md"])
        monkeypatch.setattr(coverage, "uncommitted_paths", boom)
        info = coverage.resolve_changed_files(
            changed_file=[],
            use_stdin=False,
            diff_base="base",
            repo_root=tmp_path,
            allow_empty=False,
            stdin=io.StringIO(""),
        )
        assert info.excluded is None
        rendered = "\n".join(coverage.render_changed_input(info))
        assert "미커밋 변경 확인 실패" in rendered and "RuntimeError" in rendered
        assert coverage.input_warning_tail(info) is not None


# ── ④ ci_mirror 자동 선택 경로 ────────────────────────────────────────────
class TestMirrorPath:
    def test_mirror_zero_input_exits_2(self, repo, tmp_path):
        _, mir = _toolset(tmp_path)
        _assert_mirror_zero_exits_2(mir, repo)

    def test_mirror_pipe_rejected_and_stdin_consumed(self, repo, tmp_path):
        _, mir = _toolset(tmp_path)
        _assert_mirror_pipe_rejected(mir, repo)

    def test_mirror_uncommitted_warning_is_the_last_line(self, repo, tmp_path):
        _, mir = _toolset(tmp_path)
        _assert_mirror_uncommitted_tail(mir, repo)

    def test_mirror_normal_flow_unchanged(self, repo, tmp_path):
        _, mir = _toolset(tmp_path)
        _assert_mirror_normal_flow(mir, repo)

    def test_mirror_allow_empty_runs_always_jobs(self, repo, tmp_path):
        _, mir = _toolset(tmp_path)
        rc, out, err = _mirror(mir, repo, "--allow-empty")
        assert rc == 0, f"{out}{err}"
        assert "── always (exit 0)" in out and "── backend" not in out


# ── ⑤ 뮤테이션 — 가드 하나씩 지우면 위 계약 단언이 RED인가 ──────────────
def _mutate(source: Path, old: str, new: str) -> tuple[str, str]:
    original = source.read_text(encoding="utf-8")
    assert original.count(old) == 1, f"치환 대상이 1건이 아니다({original.count(old)}): {old!r}"
    mutated = original.replace(old, new, 1)
    assert mutated != original, "주입이 적용되지 않았다 — 하네스 결함"
    return original, mutated


_COV_MUTATIONS = [
    # (id, old, new, 계약 단언)
    (
        "G1-zero-guard",
        "    if not info.files and not allow_empty:\n",
        "    if False:\n",
        _assert_zero_input_exits_2,
    ),
    (
        "G2-allow-empty-ignored",
        "    if not info.files and not allow_empty:\n",
        "    if not info.files:\n",
        _assert_allow_empty_passes,
    ),
    (
        "G3-stdin-reject-removed",
        "        if stdin_pending_data(stdin):\n",
        "        if False:\n",
        _assert_piped_list_is_rejected,
    ),
    (
        "G3b-detector-blinded",
        "    return buf[0] > 0\n",
        "    return False\n",
        _assert_piped_list_is_rejected,
    ),
    (
        "G4-stdin-not-consumed",
        "        files = _clean_paths(explicit + read_stdin_paths(stdin))\n",
        "        files = _clean_paths(explicit)\n",
        _assert_stdin_flag_consumes,
    ),
    (
        "G5-file-list-removed",
        '    lines.extend(f"  - {path}" for path in info.files)\n',
        "",
        _assert_full_file_list_in_header,
    ),
    (
        "G5b-file-list-truncated",
        '    lines.extend(f"  - {path}" for path in info.files)\n',
        '    lines.extend(f"  - {path}" for path in info.files[:10])\n',
        _assert_full_file_list_in_header,
    ),
    (
        "G6-uncommitted-probe-removed",
        "            info.uncommitted = uncommitted_paths(repo_root)\n",
        "            info.uncommitted = {}\n",
        _assert_uncommitted_only_tree,
    ),
    (
        "G6b-uncommitted-warning-removed",
        "            info.uncommitted = uncommitted_paths(repo_root)\n",
        "            info.uncommitted = {}\n",
        _assert_uncommitted_warning,
    ),
    (
        "G6c-overcount-used-paths",
        "                if path not in used and path not in out:\n",
        "                if path not in out:\n",
        _assert_uncommitted_warning,
    ),
    (
        "G6d-tail-repeat-removed",
        "        tail = input_warning_tail(info)\n        if tail:\n            print(tail)\n"
        "    return 0\n",
        "    return 0\n",
        _assert_uncommitted_warning,
    ),
]


class TestMutations:
    """각 가드를 지운 사본에 계약 단언을 대면 AssertionError, 원본은 GREEN(대조)."""

    @pytest.mark.parametrize(
        ("label", "old", "new", "check"), _COV_MUTATIONS, ids=[m[0] for m in _COV_MUTATIONS]
    )
    def test_coverage_guard_mutation_turns_red(self, tmp_path, label, old, new, check):
        if "detector" in label and os.name == "nt":
            pytest.skip("POSIX 감지기 경로 전용 뮤테이션")
        digest = hashlib.sha256(_COVERAGE_PATH.read_bytes()).hexdigest()
        _original, mutated = _mutate(_COVERAGE_PATH, old, new)
        cov, _mir = _toolset(tmp_path / "mutant", coverage_src=mutated)
        mutant_repo = _fresh_repo(tmp_path / "mutant")
        with pytest.raises(AssertionError):
            check(cov, mutant_repo)
        check(_COVERAGE_PATH, _fresh_repo(tmp_path / "control"))
        assert hashlib.sha256(_COVERAGE_PATH.read_bytes()).hexdigest() == digest, label

    @pytest.mark.parametrize(
        ("label", "old", "new", "check"),
        [
            (
                "G7-tty-guard-removed",
                "    if is_tty:\n",
                "    if False:\n",
                _assert_stdin_tty_is_rejected,
            ),
            (
                "G8-non-utf8-swallowed",
                '            text = raw.decode("utf-8-sig")\n',
                '            text = raw.decode("utf-8-sig", errors="replace")\n',
                _assert_non_utf8_is_rejected,
            ),
            (
                "G9-poll-ignores-data",
                "        if available > 0:\n            return True\n",
                "",
                _assert_poll_pipe_logic,
            ),
        ],
        ids=["G7", "G8", "G9"],
    )
    def test_in_process_guard_mutation_turns_red(self, tmp_path, label, old, new, check):
        digest = hashlib.sha256(_COVERAGE_PATH.read_bytes()).hexdigest()
        _original, mutated = _mutate(_COVERAGE_PATH, old, new)
        target = tmp_path / f"cov_mutant_{label.split('-')[0]}.py"
        target.write_text(mutated, encoding="utf-8")
        mutant = _load(target, target.stem)
        with pytest.raises(AssertionError):
            check(mutant)
        check(coverage)
        assert hashlib.sha256(_COVERAGE_PATH.read_bytes()).hexdigest() == digest, label

    def test_mirror_reverted_to_direct_git_diff_turns_red(self, tmp_path):
        """M-mirror: 미러가 scope 창구 대신 git diff를 직접 부르던 형태로 돌아가면 ④가 RED."""
        digest = hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest()
        original = _MIRROR_PATH.read_text(encoding="utf-8")
        start_marker = "    info = coverage.resolve_changed_files(\n"
        end_marker = "    changed = info.files\n"
        assert original.count(start_marker) == 1 and original.count(end_marker) == 1
        start = original.index(start_marker)
        end = original.index(end_marker) + len(end_marker)
        replacement = "    changed = coverage.changed_files_from_git(args.diff_base, repo_root)\n"
        mutated = original[:start] + replacement + original[end:]
        assert mutated != original and len(mutated) == len(original) - (end - start) + len(
            replacement
        ), "주입 산술이 맞지 않는다 — 하네스 결함"

        for check in (_assert_mirror_zero_exits_2, _assert_mirror_pipe_rejected):
            name = check.__name__
            _cov, mir = _toolset(tmp_path / f"mutant_{name}", mirror_src=mutated)
            with pytest.raises(AssertionError):
                check(mir, _fresh_repo(tmp_path / f"mutant_{name}"))
            _cov, mir = _toolset(tmp_path / f"control_{name}")
            check(mir, _fresh_repo(tmp_path / f"control_{name}"))
        assert hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest() == digest

    def test_mirror_tail_repeat_removed_turns_red(self, tmp_path):
        digest = hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest()
        _original, mutated = _mutate(
            _MIRROR_PATH,
            '        if getattr(args, "input_warning_tail", None):\n'
            "            print(args.input_warning_tail)\n",
            "",
        )
        _cov, mir = _toolset(tmp_path / "mutant", mirror_src=mutated)
        with pytest.raises(AssertionError):
            _assert_mirror_uncommitted_tail(mir, _fresh_repo(tmp_path / "mutant"))
        _cov, mir = _toolset(tmp_path / "control")
        _assert_mirror_uncommitted_tail(mir, _fresh_repo(tmp_path / "control"))
        assert hashlib.sha256(_MIRROR_PATH.read_bytes()).hexdigest() == digest
