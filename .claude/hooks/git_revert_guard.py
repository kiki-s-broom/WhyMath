#!/usr/bin/env python3
"""git 원복 계열 명령의 미커밋 변경 삼킴 가드 — PreToolUse(Bash) 훅 (HARN-136).

**무엇을 막는가**: `git checkout -- <경로>` · `git restore <경로>` · `git stash` 가
아직 커밋되지 않은 작업분을 **무증상으로** 지우는 것. 에러도 안 나고 경고도 없으며,
`git status` 에서 파일이 조용히 사라질 뿐이다.

이 부류는 이 저장소에서 두 번 났다:
  · 2026-08-10 `OPS-24` — 뮤테이션 원복에 `git checkout --` 를 써서 미커밋 구현분
    +59/-6 이 통째로 소실됐다. 신규 테스트 16건이 동작을 계약으로 고정하고 있어
    복원 충실도를 기계가 판정할 수 있었을 뿐, 백업도 테스트도 없었으면 재작성이었다.
  · 2026-09-22 `EOS-128` — 시험용 태스크를 지우며 `git checkout -- backlog/events/`
    를 실행해 그 세션의 이벤트 약 10건이 소실됐다(감사 추적 단절 · 실체 무손실).

1회차 대책이 CLAUDE.md 산문이었고 **문면이 "뮤테이션 원복"으로 좁아** 일반 정리
작업에는 적용되지 않는 것처럼 읽혔다. 그래서 2회차 대책은 코드다.

**왜 "git 원복 명령"이 아니라 "그 경로에 잃을 것이 있는가"인가**: 전건 차단하면
`git checkout <branch>` 같은 정상 전환까지 막혀 워크플로가 깨진다. 그러면 사람이
게이트를 끈다. 이 가드는 대상 경로에 **실제로 미커밋 변경이 있을 때만** 차단하므로,
깨끗한 트리에서는 한 번도 발화하지 않는다.

**모른다 ≠ 아니다**: 명령을 파싱하지 못하거나(`shlex` 실패) `git status` 조회가
실패하면 "변경 없음"으로 읽지 않는다. 원복 계열로 *보이는* 명령에 한해 차단하고
사유를 말한다 — 파괴적 동작에서 판정 불가를 통과로 접으면 그것이 곧 사고다.

**한계(명시 — 막지 못하는 것을 막는다고 말하지 않는다)**:
  · 이 훅은 **Bash 도구를 경유하는 명령만** 본다. 스크립트 안에서 호출되는 git,
    다른 도구가 부르는 git, 사람이 자기 터미널에서 치는 git 에는 닿지 않는다.
  · 탐지는 명령 문자열 파싱이다. 변수·`eval`·별칭으로 감싸면 보이지 않는다.
  · 스테이징된 변경(`git restore --staged`)은 인덱스만 되돌리므로 작업 트리 손실이
    아니다 — 차단하지 않는다.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

#: 작업 트리의 미커밋 변경을 지울 수 있는 git 서브커맨드.
#: 늘릴 때의 기준은 "이것이 **아직 커밋되지 않은 것**을 없애는가"다.
REVERT_SUBCOMMANDS: frozenset[str] = frozenset({"checkout", "restore", "stash"})

#: 작업 트리를 건드리지 않는 stash 서브커맨드 — 오히려 되살리거나 조회만 한다.
SAFE_STASH_ACTIONS: frozenset[str] = frozenset({"pop", "apply", "list", "show", "branch"})

#: 스태시 *저장소*를 지우는 서브커맨드 — 작업 트리가 아니라 스태시에 잃을 것이 있다.
STASH_DESTROY_ACTIONS: frozenset[str] = frozenset({"drop", "clear"})

#: 명시적 탈출구. 사용되면 로그에 남는다 — 남지 않는 탈출구는 게이트를 끄는 것과 같다.
ESCAPE_MARKERS: tuple[str, ...] = ("#버려도됨", "#discard-ok")

#: 셸 명령을 개별 명령으로 쪼개는 구분자. 완전한 셸 파서가 아니며, 그 한계는
#: 모듈 docstring 「한계」에 적었다.
_SEPARATORS: frozenset[str] = frozenset({"&&", "||", ";", "|", "&"})

_GIT_TIMEOUT = 15


def split_commands(command: str) -> list[list[str]]:
    """한 줄의 셸 명령을 토큰 리스트들로 쪼갠다. 파싱 실패는 예외로 알린다.

    `ValueError`(따옴표 불균형 등)를 삼키지 않는다 — 호출부가 "파싱 못 했다"를
    판정에 반영해야 하기 때문이다. 조용히 빈 목록을 돌려주면 그 명령은 검사되지
    않은 채 통과하고, 그것이 정확히 이 가드가 막으려는 형태의 실패다.
    """
    tokens = shlex.split(command, comments=False)
    groups: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEPARATORS:
            groups.append([])
        else:
            groups[-1].append(token)
    return [g for g in groups if g]


def _git_index(tokens: list[str]) -> int:
    """토큰에서 `git` 실행 위치. 환경 접두(`env A=B git …`)·경로 호출도 잡는다."""
    for i, token in enumerate(tokens):
        if token == "git" or token.endswith("/git"):
            return i
    return -1


def revert_target(tokens: list[str]) -> tuple[str, list[str]] | None:
    """이 명령이 원복 계열이면 (서브커맨드, 검사할 pathspec 목록)을 돌려준다.

    pathspec 이 빈 목록이면 **저장소 전체**가 대상이다(경로 없는 `git stash`).
    원복 계열이 아니면 None — 그때는 가드가 아무 일도 하지 않는다.
    """
    idx = _git_index(tokens)
    if idx < 0:
        return None
    args = tokens[idx + 1 :]
    # `-C <경로>` 같은 git 전역 옵션을 건너뛰고 서브커맨드를 찾는다
    pos = 0
    while pos < len(args) and args[pos].startswith("-"):
        pos += 2 if args[pos] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if pos >= len(args):
        return None
    sub = args[pos]
    if sub not in REVERT_SUBCOMMANDS:
        return None
    rest = args[pos + 1 :]

    if sub == "stash":
        action = next((a for a in rest if not a.startswith("-")), "push")
        if action in SAFE_STASH_ACTIONS:
            return None
        if action in STASH_DESTROY_ACTIONS:
            return ("stash-" + action, [])
        # push/save/무인자 — 경로를 줬으면 그 경로, 아니면 저장소 전체
        paths = [a for a in rest if not a.startswith("-") and a not in ("push", "save")]
        return ("stash", paths)

    # checkout/restore — 브랜치 생성은 경로를 지우지 않는다
    if any(flag in rest for flag in ("-b", "-B", "--orphan")):
        return None
    # `--staged` 단독은 인덱스만 되돌린다(작업 트리 손실 아님)
    if sub == "restore" and "--staged" in rest and "--worktree" not in rest:
        return None
    if "--" in rest:
        paths = rest[rest.index("--") + 1 :]
    else:
        # `--` 가 없으면 남은 비-플래그 인자가 *경로일 수도* 있다(`git checkout .`).
        # 브랜치명인지 경로인지는 git 에게 묻는다 — 브랜치명이면 pathspec 조회가
        # 빈 결과를 내므로 자동으로 통과한다. 추측하지 않는다.
        paths = [a for a in rest if not a.startswith("-")]
    return (sub, paths)


def dirty_paths(cwd: str, paths: list[str]) -> tuple[list[str] | None, str]:
    """대상 경로의 미커밋 변경 목록. (목록, 상태) — 상태 ok|error:<타입>.

    목록이 비고 상태가 ok 여야 "잃을 것이 없다"이다. 상태를 무시하면 조회 실패가
    "0건"으로 위장된다 — `remote_claims.list_claims` 와 같은 계약이다.
    """
    argv = ["git", "status", "--porcelain", "--"] + paths if paths else [
        "git",
        "status",
        "--porcelain",
    ]
    try:
        proc = subprocess.run(
            argv, cwd=cwd or None, capture_output=True, text=True, timeout=_GIT_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"error:{type(exc).__name__}"
    if proc.returncode != 0:
        return None, "error:git_exit_%d" % proc.returncode
    return [line for line in proc.stdout.splitlines() if line.strip()], "ok"


def stash_entries(cwd: str) -> tuple[list[str] | None, str]:
    """스태시 목록 — `stash drop|clear` 가 지울 대상이 실재하는가."""
    try:
        proc = subprocess.run(
            ["git", "stash", "list"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"error:{type(exc).__name__}"
    if proc.returncode != 0:
        return None, "error:git_exit_%d" % proc.returncode
    return [line for line in proc.stdout.splitlines() if line.strip()], "ok"


def _log(payload: dict[str, Any]) -> None:
    log_dir = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "git_revert_blocks.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:  # 로그 실패가 작업을 막지 않는다(타입명은 남긴다)
        print(f"[git_revert_guard] 로그 기록 실패({type(exc).__name__})", file=sys.stderr)


_ADVICE = (
    "  · 뮤테이션 원복이라면: 주입 **전에** `cp` 로 뜬 백업을 `cp` 로 되돌린다.\n"
    "    git 계열 원복은 뮤테이션과 미커밋 구현분을 구분하지 못하고 둘 다 HEAD 로 되돌린다.\n"
    "  · 지금 작업분을 지키려면: 먼저 커밋하거나 `cp` 로 사본을 뜬 뒤 다시 실행한다.\n"
    "  · 정말 버려도 되는 변경이면: 그 사실을 사용자 메시지에 "
    f"{ESCAPE_MARKERS[0]} 로 명시한다(사용 사실이 로그에 남는다)."
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[git_revert_guard] 입력 파싱 실패({type(exc).__name__}) — 통과", file=sys.stderr)
        return 0

    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0

    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    now = datetime.now(UTC).isoformat()

    try:
        groups = split_commands(command)
    except ValueError as exc:
        # 파싱 실패를 "원복 아님"으로 읽지 않는다. 다만 *원복처럼 보이지도 않으면*
        # 막을 이유가 없다 — 무관한 명령까지 막으면 가드가 상시 발화한다.
        if not any(word in command for word in REVERT_SUBCOMMANDS):
            return 0
        _log({"time": now, "blocked": True, "reason": f"parse_error:{type(exc).__name__}"})
        print(
            f"[git_revert_guard] 명령을 파싱하지 못했다({type(exc).__name__}) — "
            "원복 계열 낱말이 들어 있어 차단한다.\n"
            "  판정 불가를 통과로 접지 않는다. 명령을 단순한 형태로 나눠 다시 실행하라.",
            file=sys.stderr,
        )
        return 2

    for tokens in groups:
        target = revert_target(tokens)
        if target is None:
            continue
        sub, paths = target

        if sub.startswith("stash-"):
            entries, status = stash_entries(cwd)
            if status == "ok" and not entries:
                continue  # 지울 스태시가 없다 — 잃을 것이 없다
            losing = entries or []
            scope = f"스태시 {len(losing)}건"
        else:
            changes, status = dirty_paths(cwd, paths)
            if status == "ok" and not changes:
                continue  # 그 경로에 잃을 것이 없다 — 이 가드는 여기서 침묵한다
            losing = changes or []
            scope = f"미커밋 변경 {len(losing)}건"

        escaped = any(marker in command for marker in ESCAPE_MARKERS)
        _log(
            {
                "time": now,
                "session": data.get("session_id"),
                "subcommand": sub,
                "paths": paths,
                "status": status,
                "count": len(losing),
                "escaped": escaped,
                "blocked": not escaped,
            }
        )
        if escaped:
            return 0
        if status != "ok":
            print(
                f"[git_revert_guard] `git {sub}` 차단 — 대상에 잃을 것이 있는지 "
                f"판정하지 못했다({status}).\n"
                "  모른다를 '없다'로 접으면 그것이 사고다. 저장소 상태를 확인한 뒤 다시 실행하라.\n"
                + _ADVICE,
                file=sys.stderr,
            )
            return 2
        preview = "\n".join(f"    {line}" for line in losing[:10])
        more = f"\n    … 외 {len(losing) - 10}건" if len(losing) > 10 else ""
        print(
            f"[git_revert_guard] `git {sub}` 차단 — 대상에 {scope}이 있다. "
            "이 명령은 그것을 **무증상으로** 지운다(에러도 경고도 없다).\n"
            f"{preview}{more}\n" + _ADVICE,
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
