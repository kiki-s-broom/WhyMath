"""푸시·PR 생성 시점의 CI 미러 고지 — 미러 결과 커밋이 푸시 대상 HEAD와 다르면 알린다 (HARN-209).

왜 있는가 (판정 문서 = `docs/reviews/harn209_push_time_mirror_notice_judgment_2026-10-08.md`):
  `done`의 미러 게이트(HARN-173)는 완료 선언 시점에만 선다. `/drive` 순서가 커밋 → PR(푸시) →
  `done`이라 **red 푸시 자체는 막지 못한다**(2026-09-25 EOS-24 · PR #1316). 이 모듈은 푸시·PR 생성
  **직전**에 "이 커밋은 로컬 CI 미러를 거치지 않았다"를 알리고,
  PR 본문에 싣을 도달 잡 섹션을 만든다.

고지만 한다 — 막지 않는다. 측정 전 차단은 데이터 공백(푸시 시점 불일치 빈도는 한 번도 기록된 적이
없다) 위에 강제를 얹는 것이다. 대신 평가한 모든 푸시를 로그로 남겨 공백을 메운다(훅 쪽 책임).

"코드 없는 푸시"를 가려내는 방법 (판정 문서 §4):
  `ci_job_coverage scope`로는 못 가려낸다 — 상시 잡 6개가 모든 diff에 닿고, 원 사고(EOS-24)의 누락
  스텝이 상시 잡 `harness-integrity`에 있었다. 그래서 변경 **내용**으로 정한다.
    면제 A  트렁크 대비 기여가 전부 대장 기록(`backlog/events/`·`backlog/tasks/`)이면 침묵.
    면제 B  미러 결과 커밋 ≠ HEAD여도, 두 커밋의 트렁크 대비 기여(대장 기록 제외)가 blob까지 같고
            그 미러 결과가 통과(또는 미실행)였으면 침묵 — 미러가 본 내용 그대로다.
  문서는 면제하지 않는다: 런북 한 장이 상시 잡 `infra-shell`에서 실패한 실측이 있다(2026-10-07).

이 모듈은 판정·문구만 만든다. 훅 입력 해독·로그·중복 억제·출력은
`.claude/hooks/push_mirror_notice.py`의 몫이다 (훅 파일을 얇게 두어 이 모듈을 직접 테스트한다).

한계 (명시):
  · `git commit … && git push` 같은 복합 명령은 훅 시점에 커밋이 아직 없다. 같은 명령에서 HEAD를
    옮기는 git 명령이 푸시보다 앞서면 작업 트리의 미커밋 변경을 "곧 커밋될 내용"으로 겹쳐 본다.
    `git pull`/`merge` 뒤 푸시는 병합 결과를 미리 알 수 없어 현재 HEAD로 판정한다.
  · 푸시 대상이 HEAD가 아닌 refspec(`other:branch`)·`git -C 다른경로`·`--dry-run`·삭제·태그만은
    평가하지 않는다(사유 코드를 남긴다).
  · GitHub API로 직접 커밋하는 도구(`push_files` 등)는 로컬 HEAD가 없어 대상이 아니다.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

TRIGGER_PUSH = "git_push"
TRIGGER_PR_CREATE = "pr_create"

DEFAULT_BASE = "origin/main"
DEFAULT_WORKFLOW = Path(".github/workflows/ci.yml")

#: `done`이 쓰는 대장 기록 경로 — 이 경로만 면제한다. 늘릴 때의 기준은 "`done`/`start`가 CLI로
#: 쓰는가"이지 "코드가 아닌가"가 아니다(문서는 비불활이다 — 판정 문서 §4).
BOOKKEEPING_PREFIXES: tuple[str, ...] = ("backlog/events/", "backlog/tasks/")

#: HEAD를 옮기는 git 서브커맨드 — 같은 명령에서 푸시보다 앞서면 훅 시점의 HEAD는 낡은 값이다.
HEAD_MOVING_SUBCOMMANDS: frozenset[str] = frozenset(
    {"commit", "merge", "pull", "rebase", "cherry-pick", "am", "revert", "reset"}
)

_SEPARATORS: frozenset[str] = frozenset({"&&", "||", ";", ";;", "|", "|&", "&", "(", ")"})
#: 값을 별도 인자로 받는 `git push` 옵션.
_PUSH_OPTIONS_WITH_VALUE: frozenset[str] = frozenset(
    {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
)
_GIT_TIMEOUT = 30
#: git 앞에 올 수 있는 접두 명령·환경 대입(`GIT_SSH_COMMAND=x git push`).
_COMMAND_PREFIXES: frozenset[str] = frozenset({"env", "command", "sudo", "nohup", "time"})
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# ── 푸시 계획 (명령 문자열 → 무엇을 푸시하려는가) ─────────────────────────────

PLAN_NOT_PUSH = "not_push"
PLAN_PUSH = "push"
PLAN_DELETE = "delete"
PLAN_DRY_RUN = "dry_run"
PLAN_TAGS_ONLY = "tags_only"
PLAN_OTHER_REPO = "other_repo"


@dataclass(frozen=True)
class PushPlan:
    """한 줄 셸 명령이 푸시를 하는가, 한다면 어떤 형태인가."""

    kind: str
    refspecs: tuple[str, ...] = ()
    #: 푸시보다 앞서 HEAD를 옮기는 git 명령이 같은 명령줄에 있는가.
    head_moves: bool = False
    #: `shlex` 파싱에 실패해 정규식으로 푸시 여부만 추정했는가.
    parse_failed: bool = False


def _git_subcommand(tokens: list[str]) -> tuple[str | None, list[str], bool]:
    """(서브커맨드, 그 뒤 인자, `-C`로 다른 경로를 가리키는가). git이 아니면 (None, [], False)."""
    # git은 명령 맨 앞(환경 접두 뒤)에 있어야 한다.
    # `echo git push`·`grep git push f`의 낱말은 명령이 아니다.
    idx = 0
    while idx < len(tokens) and (
        tokens[idx] in _COMMAND_PREFIXES or _ENV_ASSIGN_RE.match(tokens[idx])
    ):
        idx += 1
    if idx >= len(tokens) or not (tokens[idx] == "git" or tokens[idx].endswith("/git")):
        return None, [], False
    args = tokens[idx + 1 :]
    other_repo = False
    pos = 0
    while pos < len(args) and args[pos].startswith("-"):
        if args[pos] in ("-C", "--git-dir", "--work-tree"):
            other_repo = True
            pos += 2
        elif args[pos] == "-c":
            pos += 2
        else:
            pos += 1
    if pos >= len(args):
        return None, [], other_repo
    return args[pos], args[pos + 1 :], other_repo


def _plan_for_push_args(rest: list[str], *, head_moves: bool) -> PushPlan:
    positionals: list[str] = []
    delete = dry_run = tags = branches = False
    skip = False
    for arg in rest:
        if skip:
            skip = False
            continue
        if arg in _PUSH_OPTIONS_WITH_VALUE:
            skip = True
        elif arg in ("-d", "--delete"):
            delete = True
        elif arg in ("-n", "--dry-run"):
            dry_run = True
        elif arg == "--tags":
            tags = True
        elif arg in ("--all", "--branches", "--mirror"):
            branches = True
        elif arg.startswith("-"):
            continue
        else:
            positionals.append(arg)
    refspecs = tuple(positionals[1:])  # 첫 위치 인자는 원격 이름이다
    if dry_run:
        return PushPlan(PLAN_DRY_RUN, refspecs, head_moves)
    if delete or any(spec.startswith(":") for spec in refspecs):
        return PushPlan(PLAN_DELETE, refspecs, head_moves)
    if tags and not refspecs and not branches:
        return PushPlan(PLAN_TAGS_ONLY, refspecs, head_moves)
    return PushPlan(PLAN_PUSH, refspecs, head_moves)


#: 히어독(`<<EOF … EOF`)의 본문 — 명령이 아니라 데이터다. 본문 속 `git push` 글귀는 푸시가 아니다.
_HEREDOC_RE = re.compile(
    r"(<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2)([^\n]*)\n.*?\n[ \t]*\3[ \t]*(?=\n|$)",
    re.DOTALL,
)


def _newlines_to_separators(command: str) -> str:
    """따옴표 밖 줄바꿈은 명령 구분자(`;`)로, 따옴표 밖 줄 잇기(`\\`+줄바꿈)는 공백으로 바꾼다."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                out.append(command[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "\\" and i + 1 < len(command):
            out.append(" " if command[i + 1] == "\n" else ch + command[i + 1])
            i += 1
        elif ch == "\n":
            out.append(" ; ")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def split_command_groups(command: str) -> list[list[str]]:
    """셸 한 줄을 개별 명령(토큰 리스트)들로 쪼갠다. 따옴표 불균형 등은 `ValueError`로 알린다.

    `shlex.split`만 쓰면 `head;`처럼 단어에 붙은 `;`가 구분자로 쪼개지지 않아 그 뒤의 `git push`가
    앞 명령의 인자가 된다(2026-10-08 실사용에서 실제 푸시 명령이 이렇게 놓쳤다). 그래서
    `punctuation_chars`로 구분 기호를 토큰으로 떼고, 히어독 본문은 지우고,
    따옴표 밖 줄바꿈은 구분자로 본다.
    """
    flattened = _HEREDOC_RE.sub(lambda m: m.group(1) + m.group(4), command)
    lexer = shlex.shlex(_newlines_to_separators(flattened), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    groups: list[list[str]] = [[]]
    for token in lexer:
        if token in _SEPARATORS:
            groups.append([])
        else:
            groups[-1].append(token)
    return [stripped for g in groups if (stripped := _strip_redirections(g))]


_REDIRECT_RE = re.compile(r"^[<>&]+$")


def _strip_redirections(tokens: list[str]) -> list[str]:
    """리다이렉션(`2>&1`·`> file`·`<<EOF`)을 인자에서 뗀다 — 안 떼면 그 토큰이 refspec이 된다."""
    kept: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if _REDIRECT_RE.match(token):
            if kept and kept[-1].isdigit():
                kept.pop()  # 파일 기술자 번호(`2>`의 2)
            i += 2  # 연산자와 그 대상
            continue
        kept.append(token)
        i += 1
    return kept


def plan_from_command(command: str) -> PushPlan:
    """Bash 명령 한 줄을 푸시 계획으로 옮긴다. 푸시가 아니면 `PLAN_NOT_PUSH`.

    파싱 실패(따옴표 불균형 등)를 "푸시 아님"으로 읽지 않는다 — `git`과 `push`가 함께 보이면
    푸시로 추정하고 `parse_failed`를 남긴다. 조용히 무시하면 이 훅이 꺼진 것과 같다.
    """
    try:
        groups = split_command_groups(command)
    except ValueError:
        if re.search(r"\bgit\b[^\n]*\bpush\b", command):
            return PushPlan(PLAN_PUSH, parse_failed=True)
        return PushPlan(PLAN_NOT_PUSH)
    head_moves = False
    for group in groups:
        sub, rest, other_repo = _git_subcommand(group)
        if sub is None:
            continue
        if sub == "push":
            if other_repo:
                return PushPlan(PLAN_OTHER_REPO, head_moves=head_moves)
            return _plan_for_push_args(rest, head_moves=head_moves)
        if sub in HEAD_MOVING_SUBCOMMANDS:
            head_moves = True
    return PushPlan(PLAN_NOT_PUSH)


def refspec_targets_head(refspecs: Sequence[str], branch: str | None) -> bool:
    """refspec이 없거나, 하나라도 원본이 현재 HEAD·현재 브랜치면 True."""
    if not refspecs:
        return True
    for spec in refspecs:
        source = spec.lstrip("+").partition(":")[0]
        if source == "HEAD" or (branch is not None and source == branch):
            return True
    return False


# ── git 조회 ────────────────────────────────────────────────────────────────


class GitQueryError(RuntimeError):
    """git 조회가 0이 아닌 코드로 끝났다 — 빈 결과로 접지 않고 호출측이 '모름'으로 처리한다."""


def _git(root: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=_GIT_TIMEOUT)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise GitQueryError(f"git {args[0]} 실패(exit {proc.returncode}): {tail}")
    return proc.stdout


def head_commit(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").decode("utf-8", errors="replace").strip()


def current_branch(root: Path) -> str | None:
    """현재 브랜치 이름. detached HEAD면 None."""
    name = _git(root, "rev-parse", "--abbrev-ref", "HEAD").decode("utf-8", errors="replace")
    name = name.strip()
    return None if name in ("", "HEAD") else name


def is_bookkeeping(path: str) -> bool:
    return path.startswith(BOOKKEEPING_PREFIXES)


def contribution(root: Path, base: str, commit: str) -> dict[str, str]:
    """`base...commit`(3점 diff)이 바꾸는 경로 → 새 blob id. 삭제는 0으로 채운 id.

    3점 diff는 base와 commit의 **공통 조상** 이후 commit 쪽 변경만 낸다 — PR이 보여 주는 바로 그
    기여다. blob id까지 쥐는 이유는 경로 집합이 같아도 내용이 다를 수 있기 때문이다.
    """
    raw = _git(root, "diff", "--raw", "-z", "--no-abbrev", "--no-renames", f"{base}...{commit}")
    parts = raw.decode("utf-8", errors="replace").split("\0")
    result: dict[str, str] = {}
    i = 0
    while i + 1 < len(parts):
        fields = parts[i].lstrip(":").split()
        if len(fields) >= 4:
            result[parts[i + 1]] = fields[3]
        i += 2
    return result


def pending_paths(root: Path) -> list[str]:
    """미커밋 변경 경로(스테이징·미스테이징·추적 안 됨). 이름 변경은 새 경로만 센다."""
    raw = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = raw.decode("utf-8", errors="replace").split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":
            i += 1  # 이름 변경·복사는 원래 경로가 다음 항목으로 따라온다
    return paths


# ── 판정 ────────────────────────────────────────────────────────────────────

# 침묵 사유
SILENT_PASS = "mirror_pass"
SILENT_NOT_EXECUTED = "mirror_not_executed"
SILENT_SAME_CONTRIBUTION = "same_contribution"
SILENT_BOOKKEEPING_ONLY = "bookkeeping_only"
SILENT_NO_BRANCH_CHANGES = "no_branch_changes"
SILENT_NOT_PUSH = "not_a_push"
SILENT_UNSUPPORTED_FORM = "unsupported_push_form"
SILENT_NON_HEAD_REF = "non_head_ref"
SILENT_BODY_OK = "body_has_section"
# 고지 사유
NOTIFY_NO_RESULT = "no_result"
NOTIFY_OTHER_COMMIT = "other_commit"
NOTIFY_RESULT_UNUSABLE = "result_unusable"
NOTIFY_FAILED = "mirror_failed"
NOTIFY_HEAD_MOVES = "head_moves_with_changes"
NOTIFY_UNAVAILABLE = "unavailable"
NOTIFY_BODY_MISSING = "body_missing_section"

NOTIFY_CODES: frozenset[str] = frozenset(
    {
        NOTIFY_NO_RESULT,
        NOTIFY_OTHER_COMMIT,
        NOTIFY_RESULT_UNUSABLE,
        NOTIFY_FAILED,
        NOTIFY_HEAD_MOVES,
        NOTIFY_UNAVAILABLE,
        NOTIFY_BODY_MISSING,
    }
)

# `assess`가 쓰는 미러 상태(`done_mirror_gate`와 같은 문자열)
STATE_PASS = "pass"
STATE_NOT_EXECUTED = "not_executed"
STATE_FAIL = "fail"
STATE_UNKNOWN = "unknown"
STATE_UNAVAILABLE = "unavailable"
STATE_NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True)
class Assessment:
    """푸시 하나(또는 PR 생성 하나)에 대한 판정 — 고지할지와 그 근거."""

    code: str
    mirror_state: str = STATE_NOT_ASSESSED
    head: str | None = None
    mirror_commit: str | None = None
    #: 트렁크 대비 기여 중 대장 기록을 뺀 경로 수. 모르면 None.
    changed: int | None = None
    detail: str = ""
    error_type: str | None = None
    #: 대장 기록이 아닌 미커밋 변경(복합 명령에서 곧 커밋될 것으로 겹쳐 본 경로).
    pending_substantive: tuple[str, ...] = field(default_factory=tuple)

    @property
    def notify(self) -> bool:
        return self.code in NOTIFY_CODES


def _ci_mirror() -> Any:
    """`ci_mirror` 모듈 — 선택 의존이라 호출 시점에 임포트한다(없으면 unavailable)."""
    harness_dir = str(Path(__file__).resolve().parent)
    if harness_dir not in sys.path:
        sys.path.append(harness_dir)
    import ci_mirror  # noqa: PLC0415

    return ci_mirror


def _substantive(contrib: dict[str, str]) -> dict[str, str]:
    return {p: b for p, b in contrib.items() if not is_bookkeeping(p)}


def assess(
    root: Path,
    *,
    base: str = DEFAULT_BASE,
    head_moves: bool = False,
    result_path: Path | None = None,
) -> Assessment:
    """현재 HEAD(와 곧 커밋될 미커밋 변경)가 로컬 CI 미러를 거쳤는지 판정한다.

    조회가 실패하면 침묵하지 않고 `unavailable`(예외 타입명 포함)로 낸다 — 모른다는 통과가 아니다.
    """
    try:
        mirror = _ci_mirror()
        head = head_commit(root)
    except (ImportError, OSError, subprocess.SubprocessError, GitQueryError) as exc:
        return Assessment(
            NOTIFY_UNAVAILABLE,
            STATE_UNAVAILABLE,
            detail=f"HEAD·미러 모듈을 확인하지 못했다: {exc}",
            error_type=type(exc).__name__,
        )

    # 1) 이 푸시가 싣는 내용 — 트렁크 대비 기여(대장 기록 제외). 모르면 None.
    substantive: dict[str, str] | None
    changed_error: str | None = None
    try:
        head_contrib = contribution(root, base, head)
    except (OSError, subprocess.SubprocessError, GitQueryError) as exc:
        head_contrib = None
        changed_error = type(exc).__name__
    substantive = None if head_contrib is None else _substantive(head_contrib)

    pending_sub: tuple[str, ...] = ()
    if head_moves:
        try:
            pending_sub = tuple(p for p in pending_paths(root) if not is_bookkeeping(p))
        except (OSError, subprocess.SubprocessError, GitQueryError) as exc:
            changed_error = changed_error or type(exc).__name__
    if pending_sub:
        # 곧 만들어질 커밋은 아직 없으므로 그 커밋에 대한 미러 결과가 있을 수 없다.
        return Assessment(
            NOTIFY_HEAD_MOVES,
            STATE_UNKNOWN,
            head=head,
            changed=len(substantive or {}) + len(pending_sub),
            detail=(
                f"같은 명령이 커밋을 만든다 — 미커밋 변경 {len(pending_sub)}건이 새 커밋에 실린다"
            ),
            pending_substantive=pending_sub,
        )

    if head_contrib is not None:
        if not head_contrib:
            return Assessment(SILENT_NO_BRANCH_CHANGES, head=head, changed=0)
        if not substantive:
            return Assessment(SILENT_BOOKKEEPING_ONLY, head=head, changed=0)

    # 2) 미러 결과 대조
    path = result_path or (root / mirror.DEFAULT_RESULT_PATH)
    verdict = mirror.mirror_verdict(path, head)
    changed = None if substantive is None else len(substantive)
    if verdict.state == mirror.VERDICT_PASS:
        return Assessment(SILENT_PASS, STATE_PASS, head, head, changed)
    if verdict.state == mirror.VERDICT_NOT_EXECUTED:
        return Assessment(SILENT_NOT_EXECUTED, STATE_NOT_EXECUTED, head, head, changed)
    if verdict.state == mirror.VERDICT_FAIL:
        return Assessment(NOTIFY_FAILED, STATE_FAIL, head, head, changed, verdict.reason)

    payload = mirror.load_payload(path)
    recorded = str(payload.get("commit", "")) if payload else ""
    if not payload:
        return Assessment(
            NOTIFY_NO_RESULT, STATE_UNKNOWN, head, None, changed, verdict.reason, changed_error
        )
    if recorded != head:
        prior = _same_contribution_state(root, base, recorded, substantive, mirror, path)
        if prior in (mirror.VERDICT_PASS, mirror.VERDICT_NOT_EXECUTED):
            return Assessment(SILENT_SAME_CONTRIBUTION, STATE_PASS, head, recorded, changed)
        if prior == mirror.VERDICT_FAIL:
            # 내용이 같고 그 내용이 이미 실패로 측정됐다 — 새 커밋이라 미측정인 것과 다르다.
            return Assessment(
                NOTIFY_FAILED, STATE_FAIL, head, recorded, changed, verdict.reason, changed_error
            )
        return Assessment(
            NOTIFY_OTHER_COMMIT,
            STATE_UNKNOWN,
            head,
            recorded,
            changed,
            verdict.reason,
            changed_error,
        )
    return Assessment(
        NOTIFY_RESULT_UNUSABLE,
        STATE_UNKNOWN,
        head,
        recorded,
        changed,
        verdict.reason,
        changed_error,
    )


def _same_contribution_state(
    root: Path,
    base: str,
    recorded: str,
    substantive: dict[str, str] | None,
    mirror: Any,
    path: Path,
) -> str | None:
    """미러가 본 커밋의 기여(대장 제외)가 지금 것과 blob까지 같으면 그 미러 결과의 판정 상태.

    같지 않거나 판정할 수 없으면 None(면제하지 않는다). 모르는 것을 같다고 접지 않는다.
    """
    if substantive is None:
        return None
    try:
        before = _substantive(contribution(root, base, recorded))
    except (OSError, subprocess.SubprocessError, GitQueryError):
        return None
    if before != substantive:
        return None
    return str(mirror.mirror_verdict(path, recorded).state)


# ── CI 도달 잡 ──────────────────────────────────────────────────────────────

REACH_COMPUTED = "computed"
REACH_FAILED = "failed"
REACH_NO_WORKFLOW = "no_workflow"


@dataclass(frozen=True)
class Reach:
    """변경이 닿는 CI 잡 — 경로 필터가 깨운 잡과 상시 잡을 따로 센다."""

    status: str
    path_jobs: tuple[str, ...] = ()
    always_jobs: tuple[str, ...] = ()
    #: 로컬에서 재현할 수 없는 잡 → 사유. CI가 최종 판정한다.
    irreproducible: tuple[tuple[str, str], ...] = ()
    changed: int = 0
    base: str = DEFAULT_BASE
    error_type: str | None = None
    detail: str = ""


def compute_reach(root: Path, base: str = DEFAULT_BASE) -> Reach:
    """`ci_job_coverage`의 분류를 그대로 쓴다. 실패해도 예외 타입명을 남긴다."""
    workflow_path = root / DEFAULT_WORKFLOW
    if not workflow_path.exists():
        return Reach(REACH_NO_WORKFLOW, base=base)
    try:
        harness_dir = str(Path(__file__).resolve().parent)
        if harness_dir not in sys.path:
            sys.path.append(harness_dir)
        import ci_job_coverage as coverage  # noqa: PLC0415

        workflow = coverage.load_workflow(workflow_path)
        changed = coverage.changed_files_from_git(base, root)
        scopes = coverage.classify_jobs(workflow, changed)
    except (
        Exception
    ) as exc:  # noqa: BLE001  (도달 잡은 부가 정보 — 실패해도 고지 본문은 나가야 한다)
        return Reach(
            REACH_FAILED,
            base=base,
            error_type=type(exc).__name__,
            detail=str(exc).splitlines()[0][:160] if str(exc) else "",
        )
    path_jobs = tuple(s.name for s in scopes if s.status in (coverage.TRIGGERED, coverage.UNKNOWN))
    always_jobs = tuple(s.name for s in scopes if s.status == coverage.ALWAYS)
    covered = {s.name for s in scopes if s.status in (coverage.TRIGGERED, coverage.UNKNOWN)}
    covered |= set(always_jobs)
    irreproducible = tuple(
        (s.name, s.env.irreproducible_reason or "재현 불가")
        for s in scopes
        if s.name in covered and not s.env.reproducible_locally
    )
    return Reach(REACH_COMPUTED, path_jobs, always_jobs, irreproducible, len(changed), base)


# ── PR 본문 섹션 ────────────────────────────────────────────────────────────

SECTION_HEADING = "## CI 도달 잡"
SECTION_MARKER = "<!-- ci-reach:v1 -->"


def body_has_section(body: str | None) -> bool:
    """PR 본문에 도달 잡 섹션이 있는가 — 표지 주석이나 제목 줄 중 하나면 있다고 본다."""
    if not body:
        return False
    return SECTION_MARKER in body or any(
        line.strip() == SECTION_HEADING for line in body.splitlines()
    )


def render_pr_section(reach: Reach, assessment: Assessment | None = None) -> str:
    """PR 본문에 붙여 넣을 마크다운 섹션. 못 구했으면 그 사실을 적는다(빈 섹션 위장 금지)."""
    lines = [SECTION_HEADING, SECTION_MARKER]
    if reach.status == REACH_COMPUTED:
        lines.append(f"- 트렁크 `{reach.base}` 대비 변경 {reach.changed}건")
        lines.append(f"- 경로 필터가 깨운 잡: {', '.join(reach.path_jobs) or '(없음)'}")
        lines.append(f"- 상시 잡: {', '.join(reach.always_jobs) or '(없음)'}")
        if reach.irreproducible:
            listing = ", ".join(f"{name}({why})" for name, why in reach.irreproducible)
            lines.append(f"- 로컬 재현 불가 — CI가 판정: {listing}")
    elif reach.status == REACH_NO_WORKFLOW:
        lines.append("- 워크플로 파일이 없는 저장소 — 도달 잡 없음")
    else:
        lines.append(
            f"- 도달 잡을 계산하지 못했다({reach.error_type}) — "
            "`python3 scripts/harness/ci_job_coverage.py scope`로 직접 확인"
        )
    if assessment is not None:
        lines.append(f"- 로컬 CI 미러: {_state_phrase(assessment)}")
    return "\n".join(lines)


def _state_phrase(assessment: Assessment) -> str:
    head = (assessment.head or "?")[:12]
    if assessment.mirror_state == STATE_PASS:
        return f"커밋 `{head}` 기준 통과(또는 미러 뒤 내용 동일)"
    if assessment.mirror_state == STATE_NOT_EXECUTED:
        return f"커밋 `{head}` 기준 실행분 통과 · 미실행 검사 스텝 있음"
    if assessment.mirror_state == STATE_FAIL:
        return f"커밋 `{head}` 기준 **실패**"
    return f"커밋 `{head}` 기준 **측정되지 않음**"


# ── 고지 문구 ───────────────────────────────────────────────────────────────

_CODE_HEADLINE: dict[str, str] = {
    NOTIFY_NO_RESULT: "이 커밋에 대한 로컬 CI 미러 결과가 없다",
    NOTIFY_OTHER_COMMIT: "로컬 CI 미러 결과가 다른 커밋의 것이다",
    NOTIFY_RESULT_UNUSABLE: "로컬 CI 미러 결과를 판정할 수 없다(형식·잡 0건)",
    NOTIFY_FAILED: "로컬 CI 미러가 실패로 끝났다",
    NOTIFY_HEAD_MOVES: "같은 명령이 커밋을 만들어 새 커밋에는 미러 결과가 있을 수 없다",
    NOTIFY_UNAVAILABLE: "로컬 CI 미러 상태를 확인하지 못했다(측정 실패 — 통과가 아니다)",
}


def render_notice(
    assessment: Assessment,
    reach: Reach | None,
    *,
    trigger: str,
    section: str | None = None,
) -> str:
    """모델에게 전달할 고지문. 막지 않는다는 것과 다음 행동을 함께 적는다."""
    where = "푸시 직전" if trigger == TRIGGER_PUSH else "PR 생성 직전"
    lines: list[str] = [f"[CI 미러 고지 · {where}] HARN-209 — 막지 않는 알림입니다."]
    if assessment.code in _CODE_HEADLINE:
        head = (assessment.head or "?")[:12]
        lines.append(f"- {_CODE_HEADLINE[assessment.code]} (HEAD {head}).")
        if assessment.detail:
            lines.append(f"  · {assessment.detail.splitlines()[0]}")
        if assessment.error_type:
            lines.append(f"  · 조회 오류 타입: {assessment.error_type}")
        if assessment.changed is not None:
            lines.append(f"  · 트렁크 대비 변경(대장 기록 제외): {assessment.changed}건")
        if reach is not None and reach.status == REACH_COMPUTED:
            lines.append(
                f"  · 닿는 잡: {', '.join(reach.path_jobs) or '(경로 필터 없음)'} "
                f"+ 상시 {len(reach.always_jobs)}잡"
            )
            if reach.irreproducible:
                names = ", ".join(name for name, _ in reach.irreproducible)
                lines.append(f"  · 로컬 재현 불가(CI가 판정): {names}")
        lines.append(
            "- 푸시 전에: `python3 scripts/harness/ci_mirror.py run` — 통과 또는 미실행이면 "
            "이 고지는 사라집니다. 같은 (HEAD·사유)는 한 번만 알립니다."
        )
    if assessment.code == NOTIFY_BODY_MISSING or section is not None:
        lines.append(
            "- PR 본문에 `## CI 도달 잡` 섹션이 없습니다. 아래 블록을 본문에 붙여 넣으세요:"
        )
        if section:
            lines.append(section)
    return "\n".join(lines)


# ── 진입점: 트리거별 (평가 + 고지문) ─────────────────────────────────────────


@dataclass(frozen=True)
class NoticeResult:
    """훅이 쓰는 한 건의 결과 — `text`가 None이면 침묵한다."""

    trigger: str
    assessment: Assessment
    text: str | None = None
    reach: Reach | None = None
    parse_failed: bool = False


def _with_notice(
    assessment: Assessment, *, trigger: str, root: Path, base: str, body_check: bool
) -> NoticeResult:
    """판정이 고지 대상이면 도달 잡을 붙여 문구를 만든다. PR 생성이면 본문 섹션도 함께 본다."""
    if not assessment.notify:
        return NoticeResult(trigger, assessment)
    reach = compute_reach(root, base)
    section = render_pr_section(reach, assessment) if body_check else None
    return NoticeResult(
        trigger,
        assessment,
        render_notice(assessment, reach, trigger=trigger, section=section),
        reach,
    )


def notice_for_push(command: str, root: Path, *, base: str = DEFAULT_BASE) -> NoticeResult:
    """`git push` 명령 한 줄에 대한 고지. 푸시가 아니거나 평가할 수 없는 형태면 침묵한다."""
    plan = plan_from_command(command)
    if plan.kind == PLAN_NOT_PUSH:
        return NoticeResult(TRIGGER_PUSH, Assessment(SILENT_NOT_PUSH))
    if plan.kind != PLAN_PUSH:
        return NoticeResult(TRIGGER_PUSH, Assessment(SILENT_UNSUPPORTED_FORM, detail=plan.kind))
    try:
        branch = current_branch(root)
    except (OSError, subprocess.SubprocessError, GitQueryError):
        branch = None
    if not refspec_targets_head(plan.refspecs, branch):
        return NoticeResult(TRIGGER_PUSH, Assessment(SILENT_NON_HEAD_REF))
    assessment = assess(root, base=base, head_moves=plan.head_moves)
    result = _with_notice(assessment, trigger=TRIGGER_PUSH, root=root, base=base, body_check=False)
    return replace(result, parse_failed=plan.parse_failed)


def notice_for_pr_create(
    root: Path, *, body: str | None, head_ref: str | None, base: str = DEFAULT_BASE
) -> NoticeResult:
    """PR 생성 직전의 고지 — 미러 대조 + 본문의 도달 잡 섹션 유무.

    본문 섹션은 **트렁크 대비 대장 기록 외 변경이 있는** PR에서만 요구한다(대장 기록만인 PR은
    푸시 고지와 같은 이유로 침묵한다). 고지가 나는 PR에는 붙여 넣을 섹션을 항상 같이 싣는다.
    """
    try:
        branch = current_branch(root)
    except (OSError, subprocess.SubprocessError, GitQueryError):
        branch = None
    if head_ref and branch and head_ref != branch:
        return NoticeResult(TRIGGER_PR_CREATE, Assessment(SILENT_NON_HEAD_REF, detail=head_ref))
    assessment = assess(root, base=base)
    if (
        not assessment.notify
        and assessment.code in (SILENT_PASS, SILENT_NOT_EXECUTED, SILENT_SAME_CONTRIBUTION)
        and not body_has_section(body)
    ):
        assessment = replace(assessment, code=NOTIFY_BODY_MISSING)
    return _with_notice(
        assessment,
        trigger=TRIGGER_PR_CREATE,
        root=root,
        base=base,
        body_check=not body_has_section(body),
    )


# ── CLI ─────────────────────────────────────────────────────────────────────


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="푸시·PR 생성 시점 CI 미러 고지 (HARN-209)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (
        ("pr-section", "PR 본문에 붙일 `## CI 도달 잡` 섹션을 출력한다"),
        ("assess", "현재 HEAD를 판정해 JSON으로 출력한다 (디버그)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--base", default=DEFAULT_BASE)
        p.add_argument("--root", type=Path, default=_repo_root())
    args = parser.parse_args(argv)

    assessment = assess(args.root, base=args.base)
    if args.cmd == "assess":
        out = {
            "code": assessment.code,
            "notify": assessment.notify,
            "mirror_state": assessment.mirror_state,
            "head": assessment.head,
            "mirror_commit": assessment.mirror_commit,
            "changed": assessment.changed,
            "error_type": assessment.error_type,
        }
        print(json.dumps(out, ensure_ascii=True))
        return 0
    print(render_pr_section(compute_reach(args.root, args.base), assessment))
    return 0


if __name__ == "__main__":
    import _stdio  # 스크립트 실행이면 이 디렉터리가 sys.path[0]이다 (OPS-53)

    _stdio.ensure_utf8_stdio()
    sys.exit(main())
