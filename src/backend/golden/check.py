#!/usr/bin/env python3
"""골든 패스 검사 명령 — 하나로 다 돌린다 (GOLD-21).

쓰는 법 (저장소 어디에서 불러도 된다. 표준 라이브러리만 쓴다)
--------------------------------------------------------------
    python src/backend/golden/check.py            # 전체: 범위 검사 + CI golden-path 잡의 검사 4개
    python src/backend/golden/check.py --fast     # 빠른 쪽: 범위 + ruff + black + mypy (DB 불필요)
    python src/backend/golden/check.py --scope    # 범위 검사만
    python src/backend/golden/check.py --hook-stop  # Stop 훅 전용(stdin JSON) — 범위 검사만

왜 있는가
---------
1. **검사 명령이 하나여야 한다.** CI golden-path 잡은 ruff·black·mypy·pytest 네 스텝이다.
   로컬에서 그중 일부만 돌리고 "초록"이라고 말하는 사고가 반복됐다(CLAUDE.md 2026-09-10).
   이 파일의 `CI_STEPS`는 CI 잡의 명령과 글자까지 같고, 같은지는
   `tests/golden/test_check_command.py`가 ci.yml을 읽어 검사한다.
2. **한 스텝이 실패해도 나머지를 끝까지 돌린다.** 앞 스텝 실패가 뒤 스텝을 "안 돌림"으로
   만들면, 안 돌린 검사와 통과한 검사가 같은 화면에 섞인다.
3. **범위 규칙을 기계로 지킨다.** "golden/ 바깥은 읽기 전용"은 CLAUDE.md의 글이었다.
   글은 부탁일 뿐이라, git의 변경 목록으로 검사한다. 편집 도구가 아니라 스크립트가 직접
   쓴 파일도 잡힌다.

종료 코드
---------
0 = 전부 통과 · 1 = 하나 이상 실패 · 2 = Stop 훅 차단 신호(--hook-stop에서만)
· 3 = 판정 불가(git 저장소가 아님, 분기 지점을 못 구함 등). 3은 통과가 아니다.

출력
----
스텝마다 한 줄(PASS/FAIL · 종료 코드 · 걸린 시간)과 마지막 판정 줄을 낸다. 실패한 스텝은
출력의 끝 40줄을 stderr로 보여 주고, 전체 출력은 `.git/golden-check/<스텝>.log`에 남긴다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# ── CI와 같은 검사 스텝 ──────────────────────────────────────────────────────
#: (이름, CI의 `run:` 줄과 글자까지 같은 명령). 실행 폴더는 CI와 같이 `src/backend`다.
#: 이 표를 바꾸면 `.github/workflows/ci.yml`의 golden-path 잡도 같이 바꿔야 한다(테스트가 막는다).
CI_STEPS: tuple[tuple[str, str], ...] = (
    ("ruff", "python -m ruff check golden ../../tests/golden"),
    ("black", "python -m black --check --line-length 100 golden ../../tests/golden"),
    ("mypy", "python -m mypy --strict golden"),
    ("pytest", "python -m pytest ../../tests/golden"),
)

#: --fast가 돌리는 스텝. pytest는 실제 PostgreSQL이 필요해 빠른 쪽에서 뺀다.
FAST_STEPS: frozenset[str] = frozenset({"ruff", "black", "mypy"})

#: 실패한 스텝에서 화면에 보여 주는 출력의 줄 수(전체는 로그 파일에 있다).
_TAIL_LINES = 40

#: 검사 도구가 없을 때 알려 주는 설치 명령(CI golden-path 잡의 설치 스텝과 같다).
_INSTALL_HINT = (
    "고치는 법: cd src/backend 에서 "
    'python -m pip install -e ".[dev]" 와 python -m pip install -e ../data-pipeline 을 실행하세요.'
)

# ── 범위 검사 ────────────────────────────────────────────────────────────────
#: 골든 패스가 지나는 경로(CLAUDE.md 골든 패스 규칙 블록의 목록과 같다).
GOLDEN_PATHS: tuple[str, ...] = (
    "golden/**",
    "src/backend/golden/**",
    "tests/golden/**",
    "src/mobile/lib/golden/**",
    "src/mobile/lib/main_golden.dart",
)

#: 하네스 CLI(backlog.py)가 스스로 쓰는 대장. 세션이 손으로 고친 것이 아니다.
LEDGER_PATHS: tuple[str, ...] = ("backlog/**",)

#: 범위 검사의 비교 기준. CI·다른 원격 이름에서는 환경변수 GOLDEN_SCOPE_BASE로 바꾼다.
_DEFAULT_BASE = "origin/main"

#: 골든 패스 태스크 ID 접두. Stop 훅은 이 접두의 태스크를 진행 중인 세션에서만 검사한다.
_GOLD_PREFIX = "GOLD-"


class CheckError(Exception):
    """판정을 내릴 수 없는 상황(git 실패 등). 통과로 읽으면 안 된다."""


@dataclass(frozen=True)
class Task:
    """대장(backlog/tasks/*.yaml)에서 읽은 태스크 한 건 중 범위 검사에 필요한 부분."""

    task_id: str
    status: str
    session: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class ScopeResult:
    """범위 검사 결과."""

    allowed: tuple[str, ...]  # 허용 경로(glob)
    changed: tuple[str, ...]  # 이 브랜치가 바꾼 파일 전부
    outside: tuple[str, ...]  # 그중 허용 경로 밖의 파일
    task_ids: tuple[str, ...]  # 이 세션이 진행 중인 태스크


@dataclass(frozen=True)
class StepResult:
    """검사 스텝 하나의 결과."""

    name: str
    returncode: int
    seconds: float
    log_path: Path | None


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """glob을 정규식으로 바꾼다.

    `**/`는 폴더 0개 이상, `**`는 아무 글자, `*`·`?`는 `/`를 넘지 않는 글자다.

    끝이 `/`인 패턴은 그 폴더 아래 전부(`폴더/**`)로 읽는다. 하네스의
    `scripts/harness/pathscope.py`와 같은 뜻이다(태스크 paths를 같은 규칙으로 읽어야 한다).
    """
    pattern = pattern.strip()
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if pattern.endswith("/"):
        pattern += "**"
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def in_scope(path: str, globs: Sequence[str]) -> bool:
    """파일 하나가 허용 경로(glob 목록) 안에 있는가."""
    return any(glob_to_regex(g).match(path) for g in globs)


def _git(root: Path, *args: str) -> str:
    """git을 실행해 표준 출력을 돌려준다. 실패하면 CheckError(통과로 읽히지 않게)."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            encoding="utf-8",  # git 출력은 UTF-8이 정본이다(로캘 인코딩으로 읽지 않는다)
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckError(f"git {args[0]} 실행 실패 — {type(exc).__name__}") from exc
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()[-1:] or ["(오류 출력 없음)"]
        raise CheckError(f"git {args[0]} 종료 코드 {done.returncode} — {detail[0]}")
    return done.stdout or ""


def repo_root(start: Path) -> Path:
    """`start`가 속한 git 저장소의 맨 위 폴더."""
    return Path(_git(start, "rev-parse", "--show-toplevel").strip())


def current_branch(root: Path) -> str:
    """현재 브랜치 이름. 브랜치가 아니면(detached) 빈 문자열."""
    name = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    return "" if name == "HEAD" else name


def changed_files(root: Path, base: str) -> tuple[str, ...]:
    """이 브랜치가 바꾼 파일 = 분기 지점 이후 커밋한 변경 + 커밋 전 수정 + 새 파일.

    `-z`로 받아 한글·공백 파일명이 그대로 온다. `--no-renames`라 옮긴 파일은 옛 위치와
    새 위치가 둘 다 나온다(옛 코드를 golden으로 "옮기는" 것도 옛 코드 수정이다).
    """
    fork = _git(root, "merge-base", base, "HEAD").strip()
    if not fork:
        raise CheckError(f"분기 지점을 구하지 못함(기준 {base})")
    tracked = _git(root, "diff", "--no-renames", "--name-only", "-z", fork)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    names = {name for name in (tracked + untracked).split("\0") if name}
    return tuple(sorted(names))


_KEY_RE = re.compile(r"^([a-z_]+):\s*(.*)$")
_ITEM_RE = re.compile(r"^\s+-\s+(.*)$")


def _unquote(value: str) -> str:
    """YAML 스칼라의 바깥 따옴표를 뗀다(대장은 CLI가 쓰는 단순한 형식이다)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_task(text: str) -> Task:
    """태스크 YAML에서 id·status·session·paths만 읽는다.

    PyYAML을 쓰지 않는 이유: 이 파일은 의존성을 설치하지 않은 세션의 Stop 훅에서도 돈다.
    읽는 네 필드는 모두 맨 왼쪽에서 시작하는 한 줄 키이고, paths만 그 아래 `- 항목` 목록이다.
    """
    fields: dict[str, str] = {}
    paths: list[str] = []
    in_paths = False
    for line in text.splitlines():
        key = _KEY_RE.match(line)
        if key:
            in_paths = key.group(1) == "paths"
            if key.group(1) in ("id", "status", "session"):
                fields[key.group(1)] = _unquote(key.group(2))
            continue
        item = _ITEM_RE.match(line)
        if in_paths and item:
            paths.append(_unquote(item.group(1)))
    session = fields.get("session", "")
    return Task(
        task_id=fields.get("id", ""),
        status=fields.get("status", ""),
        session="" if session in ("null", "~") else session,
        paths=tuple(paths),
    )


def my_tasks(root: Path, branch: str) -> tuple[Task, ...]:
    """이 브랜치(세션)가 진행 중이거나 검토 대기로 올린 태스크."""
    if not branch:
        return ()
    found: list[Task] = []
    for path in sorted((root / "backlog" / "tasks").glob("*.yaml")):
        task = parse_task(path.read_text(encoding="utf-8"))
        if task.session == branch and task.status in ("in_progress", "review"):
            found.append(task)
    return tuple(found)


def finished_here(root: Path, changed: Sequence[str]) -> tuple[Task, ...]:
    """이 브랜치에서 완료 처리한 태스크 — 태스크 파일이 이 브랜치의 변경 목록에 있고 done인 것.

    `backlog.py done`은 status를 done으로, session을 비운다. 그 순간 진행 중 목록에서 빠지지만
    그 태스크가 선언하고 바꾼 파일은 main에 머지되기 전까지 변경 목록에 남는다. 그 paths를
    계속 인정하지 않으면, 완료 처리 뒤 머지 전 검사가 정상 변경을 위반으로 잡는다.
    main에 이미 있던(이 브랜치가 건드리지 않은) 끝난 태스크의 paths는 인정하지 않는다.
    """
    found: list[Task] = []
    for name in changed:
        if not glob_to_regex("backlog/tasks/*.yaml").match(name):
            continue
        path = root / name
        if not path.is_file():
            continue  # 이 브랜치에서 지운 태스크 파일
        task = parse_task(path.read_text(encoding="utf-8"))
        if task.status == "done":
            found.append(task)
    return tuple(found)


def check_scope(root: Path, base: str, tasks: Sequence[Task]) -> ScopeResult:
    """허용 경로 밖에서 바뀐 파일을 찾는다.

    허용 경로 = 골든 패스 경로 + 하네스 대장 + 이 세션 태스크가 대장에 선언한 paths.
    목록 밖 파일을 건드려야 하면 태스크 paths에 이유와 함께 선언한다(`backlog.py amend`).
    """
    allowed: list[str] = [*GOLDEN_PATHS, *LEDGER_PATHS]
    changed = changed_files(root, base)
    for task in (*tasks, *finished_here(root, changed)):
        allowed.extend(p for p in task.paths if p not in allowed)
    outside = tuple(f for f in changed if not in_scope(f, allowed))
    return ScopeResult(
        allowed=tuple(allowed),
        changed=changed,
        outside=outside,
        task_ids=tuple(t.task_id for t in tasks),
    )


def scope_message(result: ScopeResult) -> str:
    """범위 위반 안내문 — 무엇이 틀렸고 어떻게 고치는지까지 적는다(AI가 읽고 스스로 고친다)."""
    task = result.task_ids[0] if result.task_ids else "<태스크 ID>"
    lines = [
        f"ERROR 범위 위반(golden-scope): 허용 경로 밖의 파일 {len(result.outside)}개를 바꿨습니다.",
        *(f"  - {name}" for name in result.outside),
        "허용 경로: " + " · ".join(result.allowed),
        "고치는 법 (둘 중 하나):",
        "  1) 실수라면 위 변경을 되돌립니다. 필요한 기능은 golden 안에 새로 만들고"
        " 옛 코드는 import만 합니다.",
        "  2) 꼭 필요하면 이유를 대장에 선언합니다(--path는 교체라 기존 항목도 함께 적습니다):",
        f"     python3 scripts/harness/backlog.py amend {task}"
        " --path <기존 paths 전부> --path '<위 파일>' --reason '<이유>'",
    ]
    return "\n".join(lines)


def run_scope(root: Path, base: str) -> int:
    """범위 검사를 돌리고 종료 코드를 돌려준다(0 통과 · 1 위반 · 3 판정 불가)."""
    try:
        tasks = my_tasks(root, current_branch(root))
        result = check_scope(root, base, tasks)
    except (CheckError, OSError, UnicodeError) as exc:
        print(f"UNKNOWN scope — 판정 불가: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    if result.outside:
        print(scope_message(result), file=sys.stderr)
        return 1
    return 0


# ── 검사 스텝 실행 ───────────────────────────────────────────────────────────
def step_argv(command: str) -> list[str]:
    """CI 명령 문자열을 실행 인자로 바꾼다. 맨 앞 `python`은 지금 도는 인터프리터로 바꾼다.

    (PATH의 `python`이 다른 가상환경일 수 있다 — 같은 인터프리터를 쓰게 한다.)
    """
    words = command.split()
    if words[:1] != ["python"]:
        raise ValueError(f"검사 명령은 'python -m ...' 꼴이어야 한다: {command}")
    return [sys.executable, *words[1:]]


def _log_dir(root: Path) -> Path | None:
    """전체 출력을 남길 폴더(.git 안 — 추적되지 않는다). 못 만들면 None."""
    try:
        git_dir = Path(_git(root, "rev-parse", "--git-dir").strip())
        target = (git_dir if git_dir.is_absolute() else root / git_dir) / "golden-check"
        target.mkdir(parents=True, exist_ok=True)
    except (CheckError, OSError):
        return None
    return target


def run_step(name: str, argv: Sequence[str], cwd: Path, log_dir: Path | None) -> StepResult:
    """검사 하나를 돌린다. 출력은 로그 파일에 통째로 남기고, 실패하면 끝부분을 stderr로 낸다."""
    started = time.monotonic()
    try:
        done = subprocess.run(
            list(argv),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 두 출력을 나온 순서대로 한 줄기로 받는다
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        code, output = done.returncode, done.stdout or ""
    except OSError as exc:
        code, output = 127, f"실행 실패 — {type(exc).__name__}: {exc}\n"
    seconds = time.monotonic() - started
    log_path: Path | None = None
    if log_dir is not None:
        log_path = log_dir / f"{name}.log"
        try:
            log_path.write_text(output, encoding="utf-8")
        except OSError:
            log_path = None
    if code != 0:
        tail = output.splitlines()[-_TAIL_LINES:]
        print(f"── {name} 실패 출력(끝 {len(tail)}줄) ──", file=sys.stderr)
        print("\n".join(tail), file=sys.stderr)
        if "No module named" in output:
            print(_INSTALL_HINT, file=sys.stderr)
    return StepResult(name=name, returncode=code, seconds=seconds, log_path=log_path)


def run_steps(
    steps: Sequence[tuple[str, Sequence[str]]], cwd: Path, log_dir: Path | None
) -> list[StepResult]:
    """스텝을 **전부** 돌린다. 앞 스텝이 실패해도 멈추지 않는다."""
    results: list[StepResult] = []
    for name, argv in steps:
        result = run_step(name, argv, cwd, log_dir)
        verdict = "PASS" if result.returncode == 0 else "FAIL"
        where = f" · 로그 {result.log_path}" if result.returncode != 0 and result.log_path else ""
        print(f"{verdict} {name} (exit {result.returncode} · {result.seconds:.1f}초){where}")
        results.append(result)
    return results


def run_checks(root: Path, base: str, *, fast: bool) -> int:
    """범위 검사 + CI 스텝을 돌리고 마지막 판정 줄을 낸다."""
    started = time.monotonic()
    scope_code = run_scope(root, base)
    scope_word = {0: "PASS", 1: "FAIL"}.get(scope_code, "UNKNOWN")
    print(f"{scope_word} scope (exit {scope_code})")

    wanted = [(n, c) for n, c in CI_STEPS if not fast or n in FAST_STEPS]
    skipped = [n for n, _ in CI_STEPS if fast and n not in FAST_STEPS]
    results = run_steps(
        [(name, step_argv(command)) for name, command in wanted],
        cwd=root / "src" / "backend",
        log_dir=_log_dir(root),
    )
    failed = [r.name for r in results if r.returncode != 0]
    if scope_code != 0:
        failed.insert(0, "scope")
    total = time.monotonic() - started
    verdict = "FAIL" if failed else "PASS"
    summary = f"GOLDEN_CHECK={verdict} · 돌린 검사 {len(results) + 1}개 · {total:.1f}초"
    if failed:
        summary += " · 실패: " + ", ".join(failed)
    if skipped:
        # 안 돌린 검사를 통과한 검사와 섞지 않는다 — 이름을 적는다.
        summary += " · 안 돌림(--fast): " + ", ".join(skipped) + " — 완료 판정은 전체 검사로"
    print(summary)
    return 1 if failed else 0


# ── Stop 훅 ──────────────────────────────────────────────────────────────────
def hook_stop(start: Path, base: str, stdin_bytes: bytes) -> int:
    """Stop 훅 — 골든 패스 태스크를 진행 중인 세션이 범위 밖 파일을 바꿨으면 정지를 막는다(exit 2).

    막는 것은 "골든 태스크를 진행 중 + 범위 밖 변경이 확인됨" 한 가지뿐이다. 그 밖의 모든
    경우(골든 세션이 아님 · 이미 한 번 막은 재정지 · 판정 불가)는 통과한다. 판정 불가는
    조용히 넘기지 않고 이유를 stderr에 한 줄 남긴다. 훅이 개발을 볼모로 잡으면 안 된다.
    """
    try:
        payload = json.loads(stdin_bytes.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict) and payload.get("stop_hook_active"):
        return 0  # 이미 한 번 막았다 — 무한 반복을 피한다
    try:
        root = repo_root(start)
        tasks = my_tasks(root, current_branch(root))
        if not any(t.task_id.startswith(_GOLD_PREFIX) for t in tasks):
            return 0  # 골든 패스 세션이 아니다 — 관할 밖
        result = check_scope(root, base, tasks)
    except (CheckError, OSError, UnicodeError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        print(f"[golden-scope] 판정 불가 — {reason} (정지는 막지 않는다)", file=sys.stderr)
        return 0
    if result.outside:
        print(scope_message(result), file=sys.stderr)
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """명령줄 진입점."""
    parser = argparse.ArgumentParser(description="골든 패스 검사 명령 (GOLD-21)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fast", action="store_true", help="범위 + ruff + black + mypy")
    mode.add_argument("--scope", action="store_true", help="범위 검사만")
    mode.add_argument("--hook-stop", action="store_true", help="Stop 훅 전용(stdin JSON)")
    args = parser.parse_args(argv)
    base = os.environ.get("GOLDEN_SCOPE_BASE", _DEFAULT_BASE)
    here = Path(__file__).resolve().parent

    if args.hook_stop:
        return hook_stop(Path.cwd(), base, sys.stdin.buffer.read())
    try:
        root = repo_root(here)
    except CheckError as exc:
        print(f"UNKNOWN — 판정 불가: {exc}", file=sys.stderr)
        return 3
    if args.scope:
        code = run_scope(root, base)
        print("GOLDEN_SCOPE=" + {0: "PASS", 1: "FAIL"}.get(code, "UNKNOWN"))
        return code
    return run_checks(root, base, fast=args.fast)


if __name__ == "__main__":
    sys.exit(main())
