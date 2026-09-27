#!/usr/bin/env python3
"""HARN-176 — main 낡음·미머지 작업 실시간 감시기 (Kiki 요청 2026-09-26).

무엇을 보는가 — 두 축
--------------------
① **main 낡음 축** — "지금 이 체크아웃이 main보다 낡았는가"
   · 원격을 방금 받았는가(fetch) · 못 받았다면 몇 분 전 원격을 보고 있는가
   · 현재 체크아웃(HEAD)이 origin/main보다 몇 커밋 뒤처졌는가 · 원격이 지워진 브랜치 위에 있는가
   · 로컬 main 브랜치가 origin/main과 같은가
   · 이 PC에만 있는(아직 push 안 된) 커밋 · 작업 트리 변경 수
② **미머지 축** — "머지되지 않은 작업이 어디에 얼마나 있는가"
   · 이 PC에만 있는 로컬 브랜치 커밋(push 전이라 PC가 사라지면 같이 사라진다)
   · 열린 PR과 배송 상태 — `pr_delivery_audit.classify`(HARN-30)의 분류·처방을 그대로 쓴다
   · 오래 머지되지 않은 원격 브랜치 — `remote_claims.scan_stale_branches`(HARN-47)를 그대로 쓴다

왜 새 도구인가 — 기존 도구와의 경계
-----------------------------------
이 저장소에는 이미 측정기가 셋 있다. 전부 **1회성**이고, 전부 **원격 전체**를 본다:

  · `backlog.py branches`(HARN-47) — 원격 브랜치의 고립/PR 제출 분류
  · `pr_delivery_audit.py`(HARN-30) — 열린 PR의 체크런 배송 상태
  · `flow_health.py`(FLOW-HEALTH) — 원격 브랜치 전수의 drift·충돌

셋 다 "**내가 지금 서 있는 체크아웃**이 main보다 낡았는가"를 재지 않는다. 그런데 이
저장소의 반복 사고는 정확히 그 축에서 났다:

  · 2026-07-14 — 낡은 클론에서 런북을 돌려 `fill_live_cost_table.py` 부재 오류
  · 2026-08-09 — 다른 세션의 런북이 공유 클론의 브랜치를 바꿔 둔 것을 모르고 실행
  · 2026-09-01 — 낡은 로컬 대장이 이미 main에서 done인 EOS-69를 후보로 내놔 중복 구현

그리고 셋 다 1회성이라 "**언제 바뀌었는가**"를 말하지 못한다. 이 도구는 기존 측정기의
판정 로직을 **재구현하지 않고 호출**하면서 빠진 두 가지만 더한다:
(1) 로컬 체크아웃 신선도 (2) 주기 반복 + 직전 스냅샷과의 **변화 이벤트**.

설계 계약 (CLAUDE.md 준수)
--------------------------
· **측정 실패 ≠ 이상 없음** — 신호마다 `정상/주의/미측정/생략` 4상태를 낸다. 못 잰 것을
  0건으로 접지 않는다. fetch가 실패한 주기에는 "몇 분 전 원격 기준"을 병기한다 — main을
  못 봤음과 main이 안 바뀌었음은 다른 진술이다.
· **읽기 전용** — 작업 트리·로컬 브랜치·HEAD를 바꾸지 않는다. 쓰는 것은 `git fetch`가
  갱신하는 원격 추적 ref(`refs/remotes/origin/*`·하네스 claim 미러)뿐이고 `--no-fetch`로
  끈다. 작업 트리 조회는 `--no-optional-locks`로 index 기회적 갱신(= 쓰기)까지 막는다 —
  여러 세션이 함께 쓰는 Kiki 클론에서 돌아도 남의 git 명령과 index 잠금을 다투지 않는다.
  fetch는 `gc.auto=0`으로 자동 정리(gc)를 끈다 — 긴 잠금을 만들지 않기 위해서다.
· **침묵 실패 금지** — 실패 사유에 예외 타입명을 담는다. 모든 서브프로세스에 타임아웃.
· **Windows(Phaiakes9)** — git 출력은 UTF-8 명시 디코드(`remote_claims._git` · HARN-19).
  표준출력이 cp949 파일·파이프로 리다이렉트돼도 인코딩 예외로 죽지 않는다(`errors="replace"`).
· **코드 위치 ≠ 감시 대상** — `--repo-root`(기본: 현재 폴더의 저장소)를 본다. 그래서
  감시기 코드를 별도 worktree(`origin/main`)에서 돌려도 공유 클론의 브랜치를 옮길 필요가 없다.
· **GitHub API는 형제 도구를 경유한다** — HTTP 호출은 전부 `pr_delivery_audit._get`
  (리다이렉트 추종·토큰 소비·실패 원인 보존이 이미 동결된 경로)으로만 한다.

사용
----
    python3 scripts/ops/main_watch.py                 # 1회 점검 (종료 코드로 판정)
    python3 scripts/ops/main_watch.py --watch         # 실시간 감시 (Ctrl+C로 종료)
    python3 scripts/ops/main_watch.py --json          # 1회 점검 결과를 JSON으로
    python3 scripts/ops/main_watch.py --skip prs --skip branches   # 로컬 축만 (GitHub API 0회)

종료 코드 (1회 점검)
    0 — 이상 없음(측정 전부 성공)
    1 — 주의 필요(뒤처짐·미푸시·주의 PR·고립 브랜치 등)
    2 — 측정 실패가 섞여 있다 — "이상 없음"으로 읽지 말 것(주의가 함께 있어도 2가 우선)
    3 — 사용 오류(인자 오류·git 저장소가 아님)
watch 모드는 Ctrl+C로 끝나면 0이다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NoReturn, TextIO

# 이 파일은 패키지가 아니라 단독 스크립트다 — 하네스(scripts/harness)와 형제 도구
# (scripts/ops)를 top-level 모듈로 쓰므로 두 디렉터리를 경로에 올린다.
# **코드 위치 기준**이다(감시 대상 저장소 기준이 아니다): 낡은 클론을 감시할 때 그
# 클론의 낡은 하네스 모듈이 섞여 들어오면 안 되기 때문이다.
_CODE_ROOT = Path(__file__).resolve().parents[2]
for _dir in (_CODE_ROOT / "scripts" / "harness", _CODE_ROOT / "scripts" / "ops"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
if __name__ == "__main__":
    # 단독 실행이면 바이트코드 캐시(__pycache__)도 쓰지 않는다 — 감시기는 흔적을 남기지
    # 않는다. 실측(2026-09-26 런북 시뮬레이션): 캐시가 전용 worktree를 '미추적 파일 있음'
    # 으로 만들어 정리 단계의 `git worktree remove`가 거부됐다. 테스트가 import할 때는
    # 프로세스 전역 설정을 건드리지 않도록 __main__일 때만 켠다.
    sys.dont_write_bytecode = True

import pr_delivery_audit as pda  # noqa: E402 — HARN-30: PR 배송 분류·처방·API 조회
import remote_claims  # noqa: E402 — HARN-19·47: git 호출(UTF-8)·원격 브랜치 스캔
import store  # noqa: E402 — 하네스 정책(policy.yaml: 원격 claim 사용 여부)
from flow_health import DRIFT_BEHIND  # noqa: E402 — GIT-01 표류 임계(실측 골짜기)

# ── 시간 상한·주기 ─────────────────────────────────────────────────────────
GIT_TIMEOUT = 30  # 로컬 git 조회 1회 상한(초)
FETCH_TIMEOUT = 90  # 원격 가져오기 상한 — remote_claims.SCAN_FETCH_TIMEOUT과 같은 값
GH_TOKEN_TIMEOUT = 15  # `gh auth token` 상한
MIN_INTERVAL = 10  # main 확인 주기 하한(초) — 원격을 두드리는 도구라 더 짧게 하지 않는다
MIN_SLOW_INTERVAL = 60  # PR·브랜치 주기 하한 — 미인증 GitHub API 한도(IP당 60회/시) 보호
DEFAULT_INTERVAL = 60
DEFAULT_SLOW_INTERVAL = 300
DEFAULT_MAX_REF_AGE_MIN = 30  # --no-fetch일 때 믿을 수 있는 원격 ref 나이(분)

# ── 목록 상한 (한 화면·한 주기의 비용을 묶는다) ─────────────────────────────
MAX_BRANCH_PROBES = 300  # 로컬 브랜치의 '원격에 없는 커밋' rev-list 호출 상한
MAX_LISTED = 10  # 이벤트·보고서에 펼쳐 보이는 항목 수
TRUNK_LOG_LIMIT = 200  # main 전진 시 읽는 새 커밋 수 상한
PR_PAGE_SIZE = 100  # 열린 PR 목록 1페이지 — 이 저장소 실측 한 자릿수
HEARTBEAT_WIDTH = 78  # 하트비트 한 줄의 화면 폭(칸) — 80칸 터미널에서 줄바꿈되지 않게

# ── 신호 상태 ──────────────────────────────────────────────────────────────
OK = "ok"
ATTENTION = "attention"
UNMEASURED = "unmeasured"
SKIPPED = "skipped"
STATE_LABEL = {OK: "정상", ATTENTION: "주의", UNMEASURED: "미측정", SKIPPED: "생략"}
INFO = "info"  # 이벤트 수준(주의가 아닌 변화)

AXES = ("prs", "branches")  # --skip으로 끌 수 있는 축(로컬 축은 끌 수 없다 — 이 도구의 본체)
# 느린 주기에만 다시 재는 신호 — 그 사이 빠른 주기에는 직전 값을 이어 쓴다.
SLOW_SIGNAL_KEYS = frozenset({"prs", "branches"})

# 원격 브랜치 스캔의 상태 → 사람용 이름. 즉시 조치가 필요한 것은 URGENT_BRANCH_STATUSES.
BRANCH_STATUS_LABEL = {
    "isolated": "고립",
    "pr_closed": "PR 닫힘(미머지)",
    "pr_filed": "PR 제출됨",
    "active": "진행 중",
    "ported": "포팅됨",
    "unresolved": "미판정",
}
URGENT_BRANCH_STATUSES = frozenset({"isolated", "pr_closed"})

# 스쿼시 머지 커밋 제목 끝의 `(#1332)` — PR이 main에 착지했다는 오프라인 증거.
_PR_SUFFIX = re.compile(r"\(#(\d+)\)\s*$")
# origin 주소에서 GitHub `owner/name`을 읽는다(https·ssh 양쪽, 자격증명이 섞여 있어도).
_GITHUB_REMOTE = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")

EXIT_OK, EXIT_ATTENTION, EXIT_UNMEASURED, EXIT_USAGE = 0, 1, 2, 3


# ═══════════════════════════════════════════════════════════════════════════
# 데이터 모델
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Signal:
    """판정 1건 — 보고서의 한 줄이자 변화 이벤트의 비교 단위."""

    key: str  # 기계용 이름(스냅샷 사이 비교 키)
    group: str  # "main"(낡음 축) | "unmerged"(미머지 축)
    label: str  # 사람용 이름
    state: str  # OK | ATTENTION | UNMEASURED | SKIPPED
    detail: str  # 수치를 담은 한 줄 설명
    advice: str = ""  # 처방 — 주의·미측정일 때 보고서에 붙는다
    lines: list[str] = field(default_factory=list)  # 보고서에만 싣는 세부 줄


@dataclass
class LocalBranch:
    """이 PC에만 커밋이 있는 로컬 브랜치 1건."""

    name: str
    commits: int
    kind: str  # "unpushed"(upstream보다 앞섬) | "never_pushed"(원격 어디에도 없음)


@dataclass
class LocalFacts:
    """로컬 체크아웃에서 잰 사실(판정 전 원자료). None = 재지 못함(사유는 *_error)."""

    fetch_state: str = SKIPPED  # ok | failed | skipped
    fetch_error: str = ""
    fetch_seconds: float | None = None
    ref_age_seconds: float | None = None  # 원격 ref를 받은 지 몇 초 — fetch 성공 주기면 0
    ref_age_note: str = ""
    shallow: bool = False
    trunk_ref: str = ""  # 예: refs/remotes/origin/main
    trunk_sha: str | None = None
    trunk_subject: str = ""
    trunk_error: str = ""
    head_branch: str | None = None  # None = detached(head_sha가 있을 때)
    head_sha: str | None = None
    head_error: str = ""
    head_ahead: int | None = None  # HEAD에만 있는 커밋(main 대비)
    head_behind: int | None = None  # main에만 있는 커밋(= 뒤처짐)
    head_compare_error: str = ""
    head_upstream: str = ""
    head_upstream_gone: bool = False
    head_unpushed: int | None = None
    head_unpushed_error: str = ""
    local_trunk_exists: bool = False
    local_trunk_ahead: int | None = None
    local_trunk_behind: int | None = None
    local_trunk_error: str = ""
    dirty_tracked: int | None = None
    dirty_untracked: int | None = None
    dirty_error: str = ""
    unpushed_branches: list[LocalBranch] = field(default_factory=list)
    gone_branches: list[str] = field(default_factory=list)
    branches_error: str = ""
    branches_truncated: bool = False


@dataclass
class PrEntry:
    number: int
    title: str
    head_ref: str
    draft: bool
    state: str | None  # pr_delivery_audit.classify 결과 · None = 분류 못 함(토큰 없음)
    merge_state: str = ""


@dataclass
class PrAxis:
    status: str = SKIPPED  # ok | list_only(토큰 없어 목록만) | failed | skipped
    measured_at: str = ""
    error: str = ""
    token_source: str = ""
    entries: list[PrEntry] = field(default_factory=list)
    trunk_sha: str | None = None  # 측정 시점의 main — 다음 측정의 '머지 착지' 대조 기준
    landed: dict[int, str] = field(default_factory=dict)  # 직전 측정 이후 main에 착지한 PR → 커밋
    truncated: bool = False


@dataclass
class BranchEntry:
    branch: str
    status: str  # remote_claims.StaleBranch.status 그대로
    ahead: int
    age_days: float
    evidence: str = ""


@dataclass
class BranchAxis:
    status: str = SKIPPED  # ok | failed | skipped
    measured_at: str = ""
    error: str = ""
    warning: str = ""
    entries: list[BranchEntry] = field(default_factory=list)
    pr_lookup_ok: bool = True
    stale_days: int = remote_claims.STALE_BRANCH_DEFAULT_DAYS
    truncated: bool = False


@dataclass
class Snapshot:
    taken_at: str
    repo_root: str
    code_root: str
    repo_slug: str
    token_note: str
    local: LocalFacts
    prs: PrAxis
    branches: BranchAxis
    trunk_new_commits: list[str] = field(default_factory=list)  # 직전 스냅샷 이후 main 새 커밋
    trunk_rewritten: bool = False  # 직전 main이 새 main의 조상이 아니다
    signals: list[Signal] = field(default_factory=list)


@dataclass(frozen=True)
class Event:
    """직전 스냅샷과 달라진 것 1건 — watch 모드가 시각과 함께 한 줄로 낸다."""

    level: str  # INFO | ATTENTION
    text: str
    detail: tuple[str, ...] = ()


@dataclass
class Options:
    fetch: bool = True
    skip: frozenset[str] = frozenset()
    stale_days: int = remote_claims.STALE_BRANCH_DEFAULT_DAYS
    max_ref_age_min: int = DEFAULT_MAX_REF_AGE_MIN
    repo_slug: str = ""
    token_source: str = ""  # 토큰 *출처*만 담는다 — 값은 이 객체·출력 어디에도 두지 않는다
    token_note: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# git 조회 — 전부 remote_claims._git(UTF-8 디코드·프롬프트 차단) 경유
# ═══════════════════════════════════════════════════════════════════════════


class GitQueryError(RuntimeError):
    """git 조회 실패 — 메시지에 원인(예외 타입명·stderr 첫 줄)을 담는다."""


def _run_git(root: Path, *argv: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """git 실행 — 반환 코드 판정은 호출측이 한다(1이 '아니다'를 뜻하는 명령이 있다)."""
    return remote_claims._git(root, *argv, timeout=timeout)


def _git_out(root: Path, *argv: str, timeout: int = GIT_TIMEOUT) -> str:
    """git 실행 후 stdout — 실패는 원인을 담은 `GitQueryError`로 올린다(침묵 금지)."""
    what = " ".join(argv[:2])
    try:
        result = _run_git(root, *argv, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GitQueryError(f"TimeoutExpired: git {what} {timeout}초 초과") from exc
    except Exception as exc:  # noqa: BLE001 — 환경 의존(git 부재·경로 오류) · 타입명을 남긴다
        raise GitQueryError(f"{type(exc).__name__}: git {what} — {exc}") from exc
    if result.returncode != 0:
        first = (result.stderr or "").strip().splitlines()
        reason = first[0] if first else "stderr 없음"
        raise GitQueryError(f"git {what} 비0 종료({result.returncode}): {reason}")
    return result.stdout or ""


def _count(root: Path, *argv: str) -> int:
    return int(_git_out(root, "rev-list", "--count", *argv).strip() or "0")


def _left_right(root: Path, left: str, right: str) -> tuple[int, int]:
    """(left에만 있는 커밋 수, right에만 있는 커밋 수)."""
    parts = _git_out(root, "rev-list", "--left-right", "--count", f"{left}...{right}").split()
    if len(parts) != 2:
        raise GitQueryError(f"rev-list --left-right 출력 형식 이상: {parts!r}")
    return int(parts[0]), int(parts[1])


def _short_ref(ref: str) -> str:
    """refs/remotes/origin/main → origin/main (사람이 쓰는 이름)."""
    for prefix in ("refs/remotes/", "refs/heads/"):
        if ref.startswith(prefix):
            return ref[len(prefix) :]
    return ref


def _trunk_branch(trunk_ref: str) -> str:
    """refs/remotes/origin/main → main (로컬 브랜치 이름)."""
    prefix = remote_claims.REMOTE_REF_PREFIX
    return trunk_ref[len(prefix) :] if trunk_ref.startswith(prefix) else trunk_ref


def _fetch(root: Path) -> tuple[str, str, float]:
    """원격 가져오기 — (상태, 실패 사유, 소요 초).

    refspec을 명시하는 이유: 단일 브랜치 클론은 기본 refspec이 main 하나라 다른 브랜치가
    안 온다(`scan_stale_branches`와 같은 refspec). `gc.auto=0`·`maintenance.auto=false`는
    fetch 뒤에 자동으로 붙는 정리 작업을 끈다 — 공유 클론에서 긴 잠금을 만들지 않는다.
    """
    started = time.monotonic()
    try:
        result = _run_git(
            root,
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "fetch",
            "--quiet",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            timeout=FETCH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        return "failed", f"TimeoutExpired: {FETCH_TIMEOUT}초 안에 끝나지 않았다", elapsed
    except Exception as exc:  # noqa: BLE001 — 환경 의존 · 타입명을 남긴다
        return "failed", f"{type(exc).__name__}: {exc}", time.monotonic() - started
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        kind = remote_claims._classify_failure(result.stderr or "")
        first = (result.stderr or "").strip().splitlines()
        reason = first[0] if first else "stderr 없음"
        return "failed", f"git fetch 비0 종료({result.returncode} · {kind}): {reason}", elapsed
    return "ok", "", elapsed


def _measure_trunk(root: Path, lf: LocalFacts) -> None:
    name = _short_ref(lf.trunk_ref)
    try:
        probe = _run_git(root, "rev-parse", "--verify", "--quiet", f"{lf.trunk_ref}^{{commit}}")
    except Exception as exc:  # noqa: BLE001 — 환경 의존 · 타입명을 남긴다
        lf.trunk_error = f"{type(exc).__name__}: {name} 조회 실패 — {exc}"
        return
    if probe.returncode != 0:
        lf.trunk_error = (
            f"{_josa(name, '이', '가')} 이 클론에 없다 — "
            "원격을 한 번도 받지 못했거나 원격에 그 브랜치가 없다"
        )
        return
    lf.trunk_sha = probe.stdout.strip()
    try:
        lf.trunk_subject = _git_out(root, "log", "-1", "--format=%s", lf.trunk_sha).strip()
    except GitQueryError as exc:
        lf.trunk_subject = f"(제목 조회 실패: {exc})"


def _measure_head(root: Path, lf: LocalFacts) -> None:
    try:
        sym = _run_git(root, "symbolic-ref", "--quiet", "HEAD")
        head = _run_git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    except Exception as exc:  # noqa: BLE001 — 환경 의존 · 타입명을 남긴다
        lf.head_error = f"{type(exc).__name__}: HEAD 조회 실패 — {exc}"
        return
    if head.returncode != 0:
        lf.head_error = "HEAD가 가리키는 커밋이 없다(빈 저장소이거나 손상)"
        return
    lf.head_sha = head.stdout.strip()
    ref = sym.stdout.strip() if sym.returncode == 0 else ""
    lf.head_branch = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else None
    if not lf.trunk_sha:
        lf.head_compare_error = f"{_josa(_short_ref(lf.trunk_ref), '이', '가')} 없어 비교할 수 없다"
        return
    try:
        base = _run_git(root, "merge-base", lf.head_sha, lf.trunk_sha)
        if base.returncode == 1:
            # 공통 조상이 없으면 앞섬/뒤처짐 수는 두 이력 전체가 되어 의미가 없다 — 재지 않는다.
            hint = " — shallow 클론이라 이력이 잘렸을 수 있다" if lf.shallow else ""
            lf.head_compare_error = f"main과 공통 조상이 없다{hint}"
            return
        if base.returncode != 0:
            raise GitQueryError(f"git merge-base 비0 종료({base.returncode})")
        lf.head_ahead, lf.head_behind = _left_right(root, lf.head_sha, lf.trunk_sha)
        if lf.head_branch is None:
            # detached HEAD의 커밋은 브랜치 목록에 안 나오므로 여기서 잰다.
            lf.head_unpushed = _count(root, lf.head_sha, "--not", "--remotes=origin")
    except (GitQueryError, subprocess.TimeoutExpired) as exc:
        lf.head_compare_error = f"{type(exc).__name__}: {exc}"


def _measure_local_branches(root: Path, lf: LocalFacts) -> None:
    """로컬 브랜치 전수 — 트렁크 대조·현재 브랜치의 upstream·이 PC에만 있는 커밋.

    `%(upstream:track)`의 `[gone]`은 "upstream을 설정했는데 그 원격 브랜치가 지워졌다"는
    뜻이다. 스쿼시 머지 후 정리된 브랜치가 대부분 이 상태인데, 그 커밋들은 main의 조상이
    아니라서 '원격 어디에도 없는 커밋'으로 세면 **머지된 작업이 미푸시로 오경보**된다.
    그래서 gone은 따로 모아 '정리 후보'로만 보인다(주의로 올리지 않는다).

    나머지는 upstream 대비 앞섬(`[ahead N]`)이 아니라 **원격 어디에도 없는 커밋 수**로 센다.
    upstream이 `origin/main`인 브랜치(`origin/main`에서 딴 뒤 `-u` 없이 push)는 앞섬이 곧
    main 대비 커밋 수라서, 이미 `origin/<브랜치>`에 올라간 커밋을 미푸시로 오경보한다.
    """
    trunk_branch = _trunk_branch(lf.trunk_ref)
    fmt = "%(refname)%09%(upstream)%09%(upstream:track)%09%(objectname)"
    try:
        listing = _git_out(root, "for-each-ref", f"--format={fmt}", "refs/heads")
    except GitQueryError as exc:
        lf.branches_error = str(exc)
        lf.head_unpushed_error = lf.head_unpushed_error or str(exc)
        return
    probes = 0
    for line in listing.splitlines():
        parts = line.split("\t")
        if len(parts) != 4 or not parts[0].startswith("refs/heads/"):
            continue
        ref, upstream, track, sha = parts
        name = ref[len("refs/heads/") :]
        if name == trunk_branch:
            lf.local_trunk_exists = True
            if not lf.trunk_sha:
                lf.local_trunk_error = (
                    f"{_josa(_short_ref(lf.trunk_ref), '이', '가')} 없어 비교할 수 없다"
                )
                continue
            try:
                lf.local_trunk_ahead, lf.local_trunk_behind = _left_right(root, sha, lf.trunk_sha)
            except GitQueryError as exc:
                lf.local_trunk_error = str(exc)
            continue  # 트렁크는 미머지 목록에 넣지 않는다 — 위 대조가 따로 본다
        commits: int | None
        if upstream and "gone" in track:
            kind, commits = "gone", None
        else:
            kind = "unpushed" if upstream else "never_pushed"
            if probes >= MAX_BRANCH_PROBES:
                lf.branches_truncated = True
                continue
            probes += 1
            try:
                commits = _count(root, sha, "--not", "--remotes=origin")
            except GitQueryError as exc:
                if name == lf.head_branch:
                    lf.head_unpushed_error = str(exc)
                else:
                    lf.branches_error = str(exc)
                continue
        if name == lf.head_branch:
            lf.head_upstream = _short_ref(upstream)
            lf.head_upstream_gone = kind == "gone"
            lf.head_unpushed = commits
            continue
        if kind == "gone":
            lf.gone_branches.append(name)
        elif commits:
            lf.unpushed_branches.append(LocalBranch(name, commits, kind))


def _measure_worktree(root: Path, lf: LocalFacts) -> None:
    # --no-optional-locks: status가 몰래 하던 index 갱신(쓰기)을 막는다 — 감시기는 읽기만 한다.
    try:
        out = _git_out(root, "--no-optional-locks", "status", "--porcelain=v1")
    except GitQueryError as exc:
        lf.dirty_error = str(exc)
        return
    tracked = untracked = 0
    for line in out.splitlines():
        if line.startswith("??"):
            untracked += 1
        elif line.strip():
            tracked += 1
    lf.dirty_tracked, lf.dirty_untracked = tracked, untracked


def measure_local(
    root: Path, opts: Options, *, trunk_ref: str, last_fetch_ok: float | None = None
) -> LocalFacts:
    """main 낡음 축의 원자료 — fetch(선택) 후 로컬 조회만 한다."""
    lf = LocalFacts(trunk_ref=trunk_ref)
    lf.shallow = remote_claims.is_shallow_repo(root)
    if opts.fetch:
        lf.fetch_state, lf.fetch_error, lf.fetch_seconds = _fetch(root)
    if lf.fetch_state == "ok":
        lf.ref_age_seconds = 0.0
    elif last_fetch_ok is not None:
        # 감시 중 직전 성공 시각을 안다 — 파일 시각 추정보다 정확하다.
        lf.ref_age_seconds = max(0.0, time.time() - last_fetch_ok)
    else:
        lf.ref_age_seconds, note = remote_claims.remote_refs_age_seconds(root)
        if lf.ref_age_seconds is None:
            lf.ref_age_note = note
    _measure_trunk(root, lf)
    _measure_head(root, lf)
    _measure_local_branches(root, lf)
    _measure_worktree(root, lf)
    return lf


def trunk_delta(root: Path, old: str, new: str) -> tuple[list[str], bool]:
    """직전 main → 지금 main 사이 새 커밋('sha 제목' 목록)과 이력 재작성 여부."""
    try:
        ancestor = _run_git(root, "merge-base", "--is-ancestor", old, new)
    except Exception as exc:  # noqa: BLE001 — 환경 의존 · 타입명을 남긴다
        return [f"(새 커밋 목록 조회 실패: {type(exc).__name__})"], False
    if ancestor.returncode == 1:
        return [], True
    if ancestor.returncode != 0:
        return [f"(새 커밋 목록 조회 실패: merge-base 비0 종료 {ancestor.returncode})"], False
    try:
        out = _git_out(
            root, "log", f"--max-count={TRUNK_LOG_LIMIT}", "--format=%h %s", f"{old}..{new}"
        )
    except GitQueryError as exc:
        return [f"(새 커밋 목록 조회 실패: {exc})"], False
    return [line for line in out.splitlines() if line.strip()], False


def landed_pr_numbers(root: Path, old: str | None, new: str | None) -> dict[int, str]:
    """old..new 사이 main 커밋 중 제목이 `(#N)`으로 끝나는 것 — PR N이 main에 착지했다."""
    if not old or not new or old == new:
        return {}
    try:
        out = _git_out(
            root, "log", f"--max-count={TRUNK_LOG_LIMIT}", "--format=%h%x09%s", f"{old}..{new}"
        )
    except GitQueryError:
        return {}  # 모르면 비워 둔다 — 'PR 사라짐'은 그때 '확인 불가'로 말한다
    landed: dict[int, str] = {}
    for line in out.splitlines():
        sha, _, subject = line.partition("\t")
        match = _PR_SUFFIX.search(subject)
        if match:
            landed.setdefault(int(match.group(1)), sha.strip())
    return landed


# ═══════════════════════════════════════════════════════════════════════════
# 미머지 축 — PR(HARN-30 경유)·원격 브랜치(HARN-47 경유)
# ═══════════════════════════════════════════════════════════════════════════


def repo_slug_from_origin(root: Path) -> str:
    """origin 주소에서 GitHub `owner/name` — GitHub이 아니면 빈 문자열(주소는 출력하지 않는다)."""
    try:
        url = _git_out(root, "remote", "get-url", "origin").strip()
    except GitQueryError:
        return ""
    match = _GITHUB_REMOTE.search(url)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def resolve_token(use_gh: bool) -> tuple[str, str]:
    """(토큰 출처, 비고) — **값은 반환하지도 출력하지도 않는다**.

    `gh auth token`에서 빌린 토큰은 이 프로세스의 `GH_TOKEN`에만 둔다. 그러면 형제 도구의
    `_auth_args`(HARN-30)와 `remote_claims._fetch_pr_states`(HARN-78)가 그대로 읽는다 —
    토큰을 인자로 넘기는 새 경로를 만들지 않는다. 프로세스가 끝나면 사라진다.
    """
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return name, f"{name} 환경변수"
    if not use_gh:
        return "", "토큰 없음(--no-gh)"
    gh = shutil.which("gh")
    if not gh:
        return "", "토큰 없음 — GITHUB_TOKEN·GH_TOKEN 미설정, gh CLI 미설치"
    try:
        result = subprocess.run(
            [gh, "auth", "token"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GH_TOKEN_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return "", f"토큰 없음 — gh auth token 실패({type(exc).__name__})"
    token = (result.stdout or "").strip()
    if result.returncode != 0 or not token or any(ch.isspace() for ch in token):
        return "", f"토큰 없음 — gh auth token 비0 종료({result.returncode}) · gh auth login 필요"
    os.environ["GH_TOKEN"] = token
    return "gh", "gh auth token(이 프로세스 안에서만)"


def _required_checks(rules: object) -> set[str]:
    """브랜치 규칙 응답 → 필수 체크 이름 집합(pr_delivery_audit.main과 같은 해석)."""
    if not isinstance(rules, list):
        return set()
    return {
        check["context"]
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks"
        for check in rule.get("parameters", {}).get("required_status_checks", [])
        if isinstance(check, dict) and "context" in check
    }


def measure_prs(
    root: Path,
    opts: Options,
    *,
    trunk_branch: str,
    trunk_sha: str | None,
    prev: PrAxis | None,
) -> PrAxis:
    """열린 PR — 토큰이 있으면 HARN-30 분류(처방 포함), 없으면 목록만.

    `pr_delivery_audit._get`·`_merge_state`는 측정 실패를 `SystemExit(메시지)`로 올린다
    (1회성 CLI의 계약). 감시 루프는 그 한 번으로 끝나면 안 되므로 여기서 받아 **미측정**
    으로 낮춘다 — 메시지(HTTP 상태·원인)는 그대로 보존한다.
    """
    axis = PrAxis(
        status="failed",
        measured_at=_now_iso(),
        token_source=opts.token_source,
        trunk_sha=trunk_sha,
    )
    repo = opts.repo_slug
    if not repo:
        axis.error = "GitHub 저장소 이름을 모른다 — origin이 GitHub 주소가 아니다(--repo로 지정)"
        return axis
    try:
        required: set[str] = set()
        if opts.token_source:
            status, rules = pda._get(f"/repos/{repo}/rules/branches/{trunk_branch}")
            required = _required_checks(rules)
            if not required:
                # 규칙을 못 읽었거나 필수 체크가 0건 — 어느 쪽이든 배송 분류의 기준이 없다.
                axis.error = (
                    f"필수 체크를 읽지 못했다(HTTP {status}) — 배송 분류 불가 · "
                    f"응답 앞부분: {str(rules)[:160]}"
                )
                return axis
        status, prs = pda._get(f"/repos/{repo}/pulls?state=open&per_page={PR_PAGE_SIZE}")
        if not isinstance(prs, list):
            axis.error = f"열린 PR 목록 조회 실패(HTTP {status}) — {str(prs)[:160]}"
            return axis
        for pr in prs:
            state: str | None = None
            merge_state = ""
            if opts.token_source:
                sha = pr["head"]["sha"]
                status, checks = pda._get(f"/repos/{repo}/commits/{sha}/check-runs?per_page=100")
                if not isinstance(checks, dict) or "check_runs" not in checks:
                    # 체크런을 못 읽은 것을 '체크런 0건'(NO_CHECKS)으로 접지 않는다.
                    axis.error = (
                        f"PR #{pr['number']} 체크런 조회 실패(HTTP {status}) — "
                        f"{str(checks)[:160]}"
                    )
                    return axis
                runs = {
                    run["name"]: (
                        run.get("conclusion") if run.get("status") == "completed" else None
                    )
                    for run in checks["check_runs"]
                }
                merge_state, _ = pda._merge_state(repo, pr)
                state = pda.classify(required, runs, mergeable_state=merge_state)
            axis.entries.append(
                PrEntry(
                    number=int(pr["number"]),
                    title=str(pr.get("title", "")),
                    head_ref=str((pr.get("head") or {}).get("ref", "")),
                    draft=bool(pr.get("draft", False)),
                    state=state,
                    merge_state=merge_state,
                )
            )
        axis.truncated = len(prs) >= PR_PAGE_SIZE
    except SystemExit as exc:
        axis.entries = []
        axis.error = str(exc.code)
        return axis
    except (KeyError, TypeError, ValueError) as exc:
        axis.entries = []
        axis.error = f"{type(exc).__name__}: PR 응답 형식 이상 — {exc}"
        return axis
    axis.status = "ok" if opts.token_source else "list_only"
    axis.landed = landed_pr_numbers(root, prev.trunk_sha if prev else None, trunk_sha)
    return axis


def _active_branches(root: Path) -> tuple[frozenset[str], str]:
    """원격 claim 대장의 '지금 작업 중인 브랜치' — `flow_health._active_branches`와 같은 재료.

    그 함수를 그대로 부르지 않는 이유: 그것은 **감시 대상 저장소**의 `scripts/harness`를
    경로에 올려 하네스 모듈을 찾는다. 이 도구는 코드 위치(worktree)와 감시 대상(공유 클론)이
    다를 수 있어서, 그렇게 하면 낡은 클론의 하네스 모듈이 섞여 들어온다. 여기서는 코드
    위치에서 이미 import한 모듈만 쓴다. 실패는 빈 집합이 아니라 **사유와 함께** 올린다.
    """
    try:
        policy, _ = store.load_policy(root)
        if not policy.remote_claims:
            return frozenset(), ""
        claims, status = remote_claims.list_claims(root, with_meta=True)
    except Exception as exc:  # noqa: BLE001 — 환경 의존(네트워크·권한) · 타입명을 남긴다
        return frozenset(), f"원격 claim 조회 실패({type(exc).__name__}: {exc})"
    if status != "ok":
        return frozenset(), f"원격 claim 조회 실패(status={status})"
    return frozenset(c.branch for c in claims if getattr(c, "branch", None)), ""


def measure_branches(root: Path, opts: Options) -> BranchAxis:
    """오래 머지되지 않은 원격 브랜치 — HARN-47 스캔을 그대로 쓴다(fetch는 감시기가 이미 했다)."""
    axis = BranchAxis(status="failed", measured_at=_now_iso(), stale_days=opts.stale_days)
    active, warning = _active_branches(root)
    if warning:
        axis.warning = f"{warning} — 진행 중 브랜치가 고립으로 오분류될 수 있다"
    scan = remote_claims.scan_stale_branches(
        root, days_threshold=opts.stale_days, fetch=False, active_branches=active
    )
    if scan.status != "ok":
        axis.error = f"{scan.status}: {scan.message or '사유 미상'}"
        return axis
    axis.status = "ok"
    axis.pr_lookup_ok = scan.pr_lookup_ok
    axis.error = "" if scan.pr_lookup_ok else (scan.pr_lookup_error or "사유 미상")
    axis.truncated = scan.truncated
    if scan.pr_state_lookup_ok is False and any(b.status == "pr_filed" for b in scan.stale):
        note = f"PR 열림/닫힘 미확인({scan.pr_state_lookup_error or '사유 미상'})"
        axis.warning = f"{axis.warning} · {note}" if axis.warning else note
    axis.entries = [
        BranchEntry(b.branch, b.status, b.ahead, round(b.age_days, 1), b.evidence)
        for b in scan.stale
    ]
    return axis


# ═══════════════════════════════════════════════════════════════════════════
# 판정 — 원자료 → 신호 (순수 함수 · 네트워크·git 없음)
# ═══════════════════════════════════════════════════════════════════════════


def _josa(word: str, with_final: str, without_final: str) -> str:
    """받침 유무로 조사를 고른다 — `origin/main과`·`master와`처럼 읽히게 한다.

    한글이면 마지막 글자의 받침으로, 영문이면 한국어 발음의 받침 근사로 가른다
    (l·m·n·ng로 끝나면 받침이 있다: main→메인). 완벽한 음운 규칙이 아니라 화면 가독용이다.
    """
    last = word.rstrip()[-1:] if word.strip() else ""
    if "가" <= last <= "힣":
        has_final = (ord(last) - ord("가")) % 28 != 0
    else:
        low = word.rstrip().lower()
        has_final = low.endswith(("l", "m", "n", "ng"))
    return word + (with_final if has_final else without_final)


def _clip(text: str, limit: int) -> str:
    """제목이 길면 잘라 말줄임표를 붙인다 — 잘렸다는 사실이 보이게 한다."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _prescription(state: str) -> str:
    """HARN-30 처방 문구(터미널용) — 마크다운 강조 기호는 화면에서 소음이라 뺀다."""
    return pda.PRESCRIPTION.get(state, "").replace("**", "")


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "방금 전"
    if minutes < 120:
        return f"{minutes}분 전"
    return f"{minutes // 60}시간 전"


def _age_note(lf: LocalFacts) -> str:
    """fetch를 이번에 못 했으면 main 비교 수치에 '몇 분 전 원격 기준'을 붙인다(③)."""
    if lf.fetch_state == "ok":
        return ""
    if lf.ref_age_seconds is None:
        return " (원격 기준 시점 모름)"
    return f" (원격 기준: {_ago(lf.ref_age_seconds)})"


def _where(lf: LocalFacts) -> str:
    if lf.head_sha is None:
        return "(HEAD 없음)"
    return lf.head_branch if lf.head_branch else f"detached@{lf.head_sha[:7]}"


def _local_signals(lf: LocalFacts, opts: Options) -> list[Signal]:
    out: list[Signal] = []
    trunk = _short_ref(lf.trunk_ref)
    trunk_branch = _trunk_branch(lf.trunk_ref)
    note = _age_note(lf)

    def add(key: str, label: str, state: str, detail: str, advice: str = "") -> Signal:
        sig = Signal(key, "main", label, state, detail, advice)
        out.append(sig)
        return sig

    # 1) 원격 가져오기
    if lf.fetch_state == "ok":
        add("fetch", "원격 가져오기", OK, f"성공({lf.fetch_seconds or 0:.1f}초)")
    elif lf.fetch_state == SKIPPED:
        add("fetch", "원격 가져오기", SKIPPED, "생략(--no-fetch) — 이미 받아 둔 원격 ref로 판정")
    else:
        add(
            "fetch",
            "원격 가져오기",
            UNMEASURED,
            f"실패 — {lf.fetch_error}",
            "네트워크·인증을 확인한다. 아래 main 비교는 마지막으로 받아 둔 원격 기준이다",
        )

    # 2) 원격 기준 시점 — 이번에 받지 못했을 때만 따로 판정한다
    if lf.fetch_state != "ok":
        limit = opts.max_ref_age_min
        if lf.ref_age_seconds is None:
            add(
                "ref_age",
                "원격 기준 시점",
                UNMEASURED,
                f"원격 ref를 언제 받았는지 알 수 없다({lf.ref_age_note or '사유 미상'})",
                "git fetch origin 후 다시 본다",
            )
        elif lf.ref_age_seconds > limit * 60:
            add(
                "ref_age",
                "원격 기준 시점",
                UNMEASURED,
                f"원격 ref가 {_ago(lf.ref_age_seconds)} 것 — {limit}분보다 낡아 "
                "main 비교를 믿을 수 없다",
                "git fetch origin 후 다시 본다",
            )
        else:
            add("ref_age", "원격 기준 시점", OK, f"원격 ref {_ago(lf.ref_age_seconds)} 기준")

    # 3) origin/main
    if lf.trunk_sha:
        add("trunk", trunk, OK, f"{lf.trunk_sha[:7]} 「{lf.trunk_subject}」")
    else:
        add("trunk", trunk, UNMEASURED, lf.trunk_error or "읽지 못했다", "git fetch origin")

    # 4) 현재 체크아웃
    label = "현재 체크아웃"
    at = f"{_where(lf)} @ {lf.head_sha[:7]}" if lf.head_sha else ""
    on_trunk = lf.head_branch == trunk_branch
    if lf.head_sha is None:
        add("head", label, UNMEASURED, lf.head_error or "HEAD를 읽지 못했다")
    elif lf.head_behind is None or lf.head_ahead is None:
        add(
            "head",
            label,
            UNMEASURED,
            f"{at} — {_josa(trunk, '과', '와')} 비교 불가: {lf.head_compare_error}",
        )
    elif on_trunk and lf.head_behind > 0:
        add(
            "head",
            label,
            ATTENTION,
            f"{at} — {trunk}보다 {lf.head_behind}커밋 뒤처짐{note}",
            "git pull --ff-only (작업 트리에 변경이 있으면 먼저 누구 것인지 확인)",
        )
    elif on_trunk and lf.head_ahead > 0:
        add(
            "head",
            label,
            ATTENTION,
            f"{at} — {trunk}에 없는 로컬 커밋 {lf.head_ahead}개(main 직접 커밋){note}",
            "main은 보호 브랜치라 push가 거부된다 — 새 브랜치로 옮겨 PR을 연다",
        )
    elif lf.head_upstream_gone:
        add(
            "head",
            label,
            ATTENTION,
            f"{at} — 원격에서 지워진 브랜치 위에 있다(머지 후 정리됐을 수 있다) · "
            f"{trunk}보다 {lf.head_behind}커밋 뒤처짐{note}",
            f"git switch {trunk_branch} 후 git pull --ff-only",
        )
    elif not on_trunk and lf.head_behind >= DRIFT_BEHIND:
        add(
            "head",
            label,
            ATTENTION,
            f"{at} — {trunk}보다 {lf.head_behind}커밋 뒤처짐(표류: {DRIFT_BEHIND}커밋 이상){note}",
            "origin/main을 병합하거나 main에서 새 브랜치를 딴다",
        )
    elif on_trunk:
        add("head", label, OK, f"{at} — {_josa(trunk, '과', '와')} 같음{note}")
    else:
        add(
            "head",
            label,
            OK,
            f"{at} — {trunk}보다 {lf.head_behind}커밋 뒤처짐 · {lf.head_ahead}커밋 앞섬{note}",
        )

    # 5) 현재 브랜치의 미푸시 커밋 (main·지워진 브랜치는 위 판정이 이미 말한다)
    if lf.head_sha is not None and not on_trunk and not lf.head_upstream_gone:
        label = "이 PC에만 있는 커밋(현재 브랜치)"
        if lf.head_unpushed is None:
            add("head_unpushed", label, UNMEASURED, lf.head_unpushed_error or "재지 못했다")
        elif lf.head_unpushed > 0:
            advice = (
                f"git push -u origin {lf.head_branch}"
                if lf.head_branch
                else "detached 상태다 — git switch -c 로 브랜치 이름을 붙여 커밋을 보존한다"
            )
            add(
                "head_unpushed",
                label,
                ATTENTION,
                f"{_where(lf)}에 원격 어디에도 없는 커밋 {lf.head_unpushed}개 — "
                "push 전에는 이 PC에만 있다",
                advice,
            )
        else:
            add("head_unpushed", label, OK, "없음")

    # 6) 로컬 main (지금 체크아웃이 main이 아닐 때 — main이면 4)가 이미 판정했다)
    if not on_trunk:
        label = f"로컬 {trunk_branch} 브랜치"
        if not lf.local_trunk_exists:
            add("local_trunk", label, OK, "없음(이 클론은 로컬 main을 만든 적이 없다)")
        elif lf.local_trunk_behind is None or lf.local_trunk_ahead is None:
            add("local_trunk", label, UNMEASURED, lf.local_trunk_error or "재지 못했다")
        elif lf.local_trunk_ahead > 0:
            add(
                "local_trunk",
                label,
                ATTENTION,
                f"로컬 {trunk_branch}에만 있는 커밋 {lf.local_trunk_ahead}개(main 직접 커밋)",
                "main은 보호 브랜치라 push가 거부된다 — 새 브랜치로 옮겨 PR을 연다",
            )
        elif lf.local_trunk_behind > 0:
            add(
                "local_trunk",
                label,
                OK,
                f"{trunk}보다 {lf.local_trunk_behind}커밋 뒤처짐 — 지금 체크아웃이 아니라 "
                f"당장 영향은 없다. {trunk_branch}로 전환하면 git pull --ff-only{note}",
            )
        else:
            add("local_trunk", label, OK, f"{_josa(trunk, '과', '와')} 같음{note}")

    # 7) 작업 트리
    if lf.dirty_tracked is None or lf.dirty_untracked is None:
        add("worktree", "작업 트리", UNMEASURED, lf.dirty_error or "재지 못했다")
    else:
        caution = (
            " — 다른 세션의 미커밋 작업일 수 있으니 되돌리기 전에 확인"
            if lf.dirty_tracked or lf.dirty_untracked
            else ""
        )
        add(
            "worktree",
            "작업 트리",
            OK,
            f"변경 {lf.dirty_tracked}파일 · 추적 안 됨 {lf.dirty_untracked}파일{caution}",
        )
    return out


def _local_branch_signal(lf: LocalFacts) -> Signal:
    label = "이 PC에만 있는 커밋(다른 로컬 브랜치)"
    if lf.branches_error:
        return Signal("local_branches", "unmerged", label, UNMEASURED, lf.branches_error)
    gone = (
        f" · 원격이 지워진 로컬 브랜치 {len(lf.gone_branches)}개(머지 여부 확인 후 정리 후보)"
        if lf.gone_branches
        else ""
    )
    lines = [f"[정리 후보] {name}" for name in lf.gone_branches[:MAX_LISTED]]
    if len(lf.gone_branches) > MAX_LISTED:
        lines.append(f"[정리 후보] … 외 {len(lf.gone_branches) - MAX_LISTED}개")
    if lf.branches_truncated:
        lines.append(f"(로컬 브랜치가 많아 앞 {MAX_BRANCH_PROBES}개만 쟀다)")
    if not lf.unpushed_branches:
        return Signal("local_branches", "unmerged", label, OK, f"없음{gone}", lines=lines)
    kind_label = {"unpushed": "push 안 한 커밋", "never_pushed": "push한 적 없는 브랜치"}
    items = [
        f"[{kind_label.get(b.kind, b.kind)}] {b.name} — {b.commits}커밋"
        for b in lf.unpushed_branches
    ]
    head = " · ".join(f"{b.name}({b.commits})" for b in lf.unpushed_branches[:5])
    more = f" 외 {len(lf.unpushed_branches) - 5}개" if len(lf.unpushed_branches) > 5 else ""
    return Signal(
        "local_branches",
        "unmerged",
        label,
        ATTENTION,
        f"{len(lf.unpushed_branches)}개 브랜치 — {head}{more}{gone}",
        "push 후 PR을 열거나, 버릴 작업이면 삭제 여부를 결정한다(이 PC가 유일한 사본이다)",
        items[:MAX_LISTED] + lines,
    )


def _pr_signal(axis: PrAxis) -> Signal:
    label = "열린 PR"
    if axis.status == SKIPPED:
        return Signal("prs", "unmerged", label, SKIPPED, "생략(--skip prs)")
    if axis.status == "failed":
        return Signal("prs", "unmerged", label, UNMEASURED, axis.error or "사유 미상")
    more = f" (앞 {PR_PAGE_SIZE}건만 봤다)" if axis.truncated else ""
    if axis.status == "list_only":
        lines = [
            f"#{e.number} {_clip(e.title, 60)} ({e.head_ref})" for e in axis.entries[:MAX_LISTED]
        ]
        return Signal(
            "prs",
            "unmerged",
            label,
            UNMEASURED,
            f"{len(axis.entries)}건 — CI·머지 상태는 못 쟀다(GitHub 토큰 없음){more}",
            "GITHUB_TOKEN 또는 GH_TOKEN을 설정하거나 gh auth login 후 다시 본다",
            lines,
        )
    buckets: dict[str, list[PrEntry]] = {}
    for entry in axis.entries:
        buckets.setdefault(entry.state or "UNCLASSIFIED", []).append(entry)
    lines: list[str] = []
    for state in sorted(buckets, key=lambda s: (s not in pda.ATTENTION, s)):
        mark = "주의" if state in pda.ATTENTION else "진행"
        lines.append(f"[{mark}] {state} {len(buckets[state])}건 — {_prescription(state)}")
        for entry in buckets[state][:MAX_LISTED]:
            draft = " [draft]" if entry.draft else ""
            lines.append(f"    #{entry.number} {_clip(entry.title, 56)}{draft}")
    attention = [e for e in axis.entries if e.state in pda.ATTENTION]
    if attention:
        return Signal(
            "prs",
            "unmerged",
            label,
            ATTENTION,
            f"{len(axis.entries)}건 중 주의 {len(attention)}건{more}",
            "아래 처방을 따른다 — 'NO_CHECKS'와 'READY_UNMERGED'는 처방이 정반대다(HARN-30)",
            lines,
        )
    return Signal(
        "prs",
        "unmerged",
        label,
        OK,
        f"{len(axis.entries)}건 — 주의 없음{more}" if axis.entries else "0건",
        lines=lines,
    )


def _branch_signal(axis: BranchAxis) -> Signal:
    label = f"오래 머지 안 된 원격 브랜치({axis.stale_days}일 이상)"
    if axis.status == SKIPPED:
        return Signal("branches", "unmerged", label, SKIPPED, "생략(--skip branches)")
    if axis.status == "failed":
        return Signal("branches", "unmerged", label, UNMEASURED, axis.error or "사유 미상")
    if not axis.pr_lookup_ok:
        return Signal(
            "branches",
            "unmerged",
            label,
            UNMEASURED,
            f"PR 대조 실패 — 고립 여부를 판정하지 못했다: {axis.error}",
        )
    counts: dict[str, int] = {}
    for entry in axis.entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    detail = " · ".join(
        f"{BRANCH_STATUS_LABEL[s]} {counts.get(s, 0)}"
        for s in ("isolated", "pr_closed", "pr_filed", "active", "ported")
    )
    lines = []
    urgent = [e for e in axis.entries if e.status in URGENT_BRANCH_STATUSES]
    for entry in urgent[:MAX_LISTED]:
        evidence = f" · {entry.evidence}" if entry.evidence else ""
        lines.append(
            f"[{BRANCH_STATUS_LABEL[entry.status]}] {entry.branch} — {entry.age_days:.0f}일 · "
            f"main 대비 {entry.ahead}커밋{evidence}"
        )
    if axis.warning:
        lines.append(f"(경고) {axis.warning}")
    if axis.truncated:
        lines.append("(원격 브랜치가 많아 일부만 쟀다)")
    if urgent:
        return Signal(
            "branches",
            "unmerged",
            label,
            ATTENTION,
            detail,
            "고립은 PR로 회수하거나 삭제, PR 닫힘은 재작업·폐기를 결정한다(backlog.py branches)",
            lines,
        )
    return Signal("branches", "unmerged", label, OK, detail, lines=lines)


def derive_signals(snap: Snapshot, opts: Options) -> list[Signal]:
    """스냅샷 원자료 → 신호 목록(보고서 순서)."""
    return [
        *_local_signals(snap.local, opts),
        _local_branch_signal(snap.local),
        _pr_signal(snap.prs),
        _branch_signal(snap.branches),
    ]


def exit_code(signals: list[Signal]) -> int:
    """미측정이 하나라도 있으면 2 — 주의가 함께 있어도 2가 우선이다(못 잰 판정은 믿지 않는다)."""
    states = {s.state for s in signals}
    if UNMEASURED in states:
        return EXIT_UNMEASURED
    if ATTENTION in states:
        return EXIT_ATTENTION
    return EXIT_OK


# ═══════════════════════════════════════════════════════════════════════════
# 변화 이벤트 — 직전 스냅샷과 비교 (순수 함수)
# ═══════════════════════════════════════════════════════════════════════════


def diff_events(prev: Snapshot, cur: Snapshot) -> list[Event]:
    """직전 스냅샷과 달라진 것만 이벤트로 — 같은 상태가 이어지면 아무것도 내지 않는다."""
    events: list[Event] = []
    p, c = prev.local, cur.local
    trunk = _short_ref(c.trunk_ref)

    # main 전진·재작성
    if p.trunk_sha and c.trunk_sha and p.trunk_sha != c.trunk_sha:
        if cur.trunk_rewritten:
            events.append(
                Event(
                    ATTENTION,
                    f"{trunk} 이력이 바뀌었다 — 직전 {p.trunk_sha[:7]}이 새 {c.trunk_sha[:7]}의 "
                    "조상이 아니다(강제 push 의심)",
                )
            )
        else:
            n = len(cur.trunk_new_commits)
            count = f"{n}개 이상" if n >= TRUNK_LOG_LIMIT else f"{n}개"
            shown = tuple(cur.trunk_new_commits[:MAX_LISTED])
            if n > MAX_LISTED:
                shown += (f"… 외 {n - MAX_LISTED}개",)
            events.append(
                Event(
                    INFO,
                    f"{trunk} 전진: {p.trunk_sha[:7]} → {c.trunk_sha[:7]} (새 커밋 {count})",
                    shown,
                )
            )

    # 체크아웃 전환·HEAD 이동
    if p.head_sha and c.head_sha:
        if p.head_branch != c.head_branch:
            events.append(
                Event(
                    ATTENTION,
                    f"체크아웃 전환: {_where(p)} → {_where(c)} — 다른 창이나 세션이 브랜치를 "
                    "바꿨을 수 있다. 진행 중인 런북이 있으면 대상 브랜치를 다시 확인한다",
                )
            )
        elif p.head_sha != c.head_sha:
            events.append(
                Event(INFO, f"HEAD 이동({_where(c)}): {p.head_sha[:7]} → {c.head_sha[:7]}")
            )

    # 작업 트리 변경 수
    before = (p.dirty_tracked, p.dirty_untracked)
    after = (c.dirty_tracked, c.dirty_untracked)
    if None not in before and None not in after and before != after:
        events.append(
            Event(
                INFO,
                f"작업 트리 변경 수: 변경 {before[0]}·추적 안 됨 {before[1]} → "
                f"변경 {after[0]}·추적 안 됨 {after[1]}",
            )
        )

    # 신호 상태 전이 (정상↔주의↔미측정)
    prev_signals = {s.key: s for s in prev.signals}
    for sig in cur.signals:
        old = prev_signals.get(sig.key)
        if old is None or old.state == sig.state:
            continue
        level = ATTENTION if sig.state in (ATTENTION, UNMEASURED) else INFO
        events.append(
            Event(
                level,
                f"{sig.label}: {STATE_LABEL[old.state]} → {STATE_LABEL[sig.state]} — {sig.detail}",
            )
        )

    events.extend(_pr_events(prev.prs, cur.prs, trunk))
    events.extend(_branch_events(prev.branches, cur.branches))
    return events


def _pr_events(prev: PrAxis, cur: PrAxis, trunk: str) -> list[Event]:
    measured = ("ok", "list_only")
    if cur.measured_at == prev.measured_at:
        return []  # 이번 주기에 다시 재지 않았다 — 비교할 새 사실이 없다
    if prev.status not in measured or cur.status not in measured:
        return []  # 한쪽이 못 쟀으면 '사라짐'을 말할 수 없다(신호 전이가 대신 말한다)
    before = {e.number: e for e in prev.entries}
    after = {e.number: e for e in cur.entries}
    events: list[Event] = []
    for number in sorted(after.keys() - before.keys()):
        entry = after[number]
        state = f" · {entry.state}" if entry.state else ""
        events.append(
            Event(INFO, f"새 PR #{number} 「{_clip(entry.title, 60)}」 ({entry.head_ref}){state}")
        )
    for number in sorted(before.keys() - after.keys()):
        entry = before[number]
        if number in cur.landed:
            events.append(
                Event(
                    INFO,
                    f"PR #{number} 머지됨 — {trunk}에 착지({cur.landed[number]}) "
                    f"「{_clip(entry.title, 60)}」",
                )
            )
        else:
            events.append(
                Event(
                    INFO,
                    f"PR #{number} 목록에서 사라짐 — 닫혔거나, 머지됐지만 main 커밋에서 "
                    f"확인하지 못했다 「{_clip(entry.title, 60)}」",
                )
            )
    for number in sorted(after.keys() & before.keys()):
        old, new = before[number].state, after[number].state
        if old and new and old != new:
            level = ATTENTION if new in pda.ATTENTION else INFO
            events.append(
                Event(
                    level,
                    f"PR #{number} 상태: {old} → {new} — {_prescription(new)}",
                )
            )
    return events


def _branch_events(prev: BranchAxis, cur: BranchAxis) -> list[Event]:
    if cur.measured_at == prev.measured_at:
        return []
    if not (prev.status == "ok" == cur.status and prev.pr_lookup_ok and cur.pr_lookup_ok):
        return []
    before = {e.branch: e for e in prev.entries}
    after = {e.branch: e for e in cur.entries}
    events: list[Event] = []
    for name in sorted(after.keys() - before.keys()):
        entry = after[name]
        level = ATTENTION if entry.status in URGENT_BRANCH_STATUSES else INFO
        events.append(
            Event(
                level,
                "오래된 미머지 브랜치 등장 "
                f"[{BRANCH_STATUS_LABEL.get(entry.status, entry.status)}] "
                f"{name} — {entry.age_days:.0f}일 · main 대비 {entry.ahead}커밋",
            )
        )
    for name in sorted(before.keys() - after.keys()):
        label = BRANCH_STATUS_LABEL.get(before[name].status, before[name].status)
        events.append(
            Event(INFO, f"미머지 브랜치 목록에서 빠짐: {name}(직전 [{label}]) — 머지·삭제됐다")
        )
    for name in sorted(after.keys() & before.keys()):
        old, new = before[name].status, after[name].status
        if old != new:
            level = ATTENTION if new in URGENT_BRANCH_STATUSES else INFO
            events.append(
                Event(
                    level,
                    f"미머지 브랜치 상태: {name} [{BRANCH_STATUS_LABEL.get(old, old)}] → "
                    f"[{BRANCH_STATUS_LABEL.get(new, new)}]",
                )
            )
    return events


# ═══════════════════════════════════════════════════════════════════════════
# 스냅샷·출력
# ═══════════════════════════════════════════════════════════════════════════


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clock() -> str:
    return datetime.now().strftime("%H:%M:%S")


def take_snapshot(
    root: Path,
    opts: Options,
    *,
    trunk_ref: str,
    prev: Snapshot | None = None,
    slow: bool = True,
    last_fetch_ok: float | None = None,
) -> Snapshot:
    """1주기 측정 — slow=False면 PR·브랜치 축은 직전 값을 그대로 이어 쓴다(비용 절약)."""
    local = measure_local(root, opts, trunk_ref=trunk_ref, last_fetch_ok=last_fetch_ok)
    snap = Snapshot(
        taken_at=_now_iso(),
        repo_root=str(root),
        code_root=str(_CODE_ROOT),
        repo_slug=opts.repo_slug,
        token_note=opts.token_note,
        local=local,
        prs=PrAxis(),
        branches=BranchAxis(stale_days=opts.stale_days),
    )
    old_trunk = prev.local.trunk_sha if prev else None
    if old_trunk and local.trunk_sha and old_trunk != local.trunk_sha:
        snap.trunk_new_commits, snap.trunk_rewritten = trunk_delta(root, old_trunk, local.trunk_sha)
    if "prs" in opts.skip:
        snap.prs = PrAxis(status=SKIPPED)
    elif slow or prev is None:
        snap.prs = measure_prs(
            root,
            opts,
            trunk_branch=_trunk_branch(trunk_ref),
            trunk_sha=local.trunk_sha,
            prev=prev.prs if prev else None,
        )
    else:
        snap.prs = prev.prs
    if "branches" in opts.skip:
        snap.branches = BranchAxis(status=SKIPPED, stale_days=opts.stale_days)
    elif slow or prev is None:
        snap.branches = measure_branches(root, opts)
    else:
        snap.branches = prev.branches
    snap.signals = derive_signals(snap, opts)
    return snap


def render_report(snap: Snapshot) -> str:
    """전체 점검 보고서 — 1회 점검과 watch 첫 화면."""
    lines = [
        f"== main·미머지 점검 (HARN-176) — {snap.taken_at} ==",
        f"감시 대상: {snap.repo_root}",
    ]
    if Path(snap.code_root) != Path(snap.repo_root):
        lines.append(f"감시기 코드: {snap.code_root}")
    if snap.repo_slug:
        lines.append(f"GitHub: {snap.repo_slug} · 토큰: {snap.token_note or '확인 안 함'}")
    if snap.local.shallow:
        lines.append(
            "(shallow 클론 — 오래된 브랜치 판정은 불가하고, main 비교는 공통 조상이 있을 때만)"
        )
    for group, title in (("main", "[1] main 신선도"), ("unmerged", "[2] 미머지 작업")):
        lines.append(title)
        for sig in (s for s in snap.signals if s.group == group):
            lines.append(f"  [{STATE_LABEL[sig.state]}] {sig.label}: {sig.detail}")
            lines.extend(f"        {extra}" for extra in sig.lines)
            if sig.advice and sig.state in (ATTENTION, UNMEASURED):
                lines.append(f"        → {sig.advice}")
    code = exit_code(snap.signals)
    attention = sum(s.state == ATTENTION for s in snap.signals)
    unmeasured = sum(s.state == UNMEASURED for s in snap.signals)
    meaning = {
        EXIT_OK: "이상 없음",
        EXIT_ATTENTION: "주의 필요",
        EXIT_UNMEASURED: "측정 실패 포함 — 이상 없음으로 읽지 말 것",
    }[code]
    lines.append(
        f"[판정] 주의 {attention}건 · 미측정 {unmeasured}건 → 종료 코드 {code} ({meaning})"
    )
    return "\n".join(lines)


def render_event(event: Event, clock: str) -> str:
    tag = "[주의]" if event.level == ATTENTION else "[변화]"
    lines = [f"[{clock}] {tag} {event.text}"]
    lines.extend(f"           {extra}" for extra in event.detail)
    return "\n".join(lines)


def render_unmeasured(signals: list[Signal], clock: str) -> str:
    items = [f"{s.label}({s.detail})" for s in signals]
    return f"[{clock}] [미측정] " + " · ".join(items)


def render_heartbeat(snap: Snapshot, clock: str) -> str:
    lf = snap.local
    parts = [f"[{clock}] 변화 없음"]
    if lf.trunk_sha:
        parts.append(f"main {lf.trunk_sha[:7]}")
    if lf.head_sha:
        behind = "?" if lf.head_behind is None else str(lf.head_behind)
        parts.append(f"{_where(lf)} 뒤처짐 {behind}")
    if snap.prs.status in ("ok", "list_only"):
        parts.append(f"PR {len(snap.prs.entries)}")
    parts.append(f"주의 {sum(s.state == ATTENTION for s in snap.signals)}")
    unmeasured = sum(s.state == UNMEASURED for s in snap.signals)
    if unmeasured:
        # 이어지는 미측정은 실패 줄을 매분 되풀이하지 않고 여기서 계속 보인다(침묵 아님).
        parts.append(f"미측정 {unmeasured}")
    # 구분자는 ASCII — '·'는 한국어 콘솔에서 2칸으로 그려질 수 있는 모호 폭 문자라
    # 제자리 덮어쓰기(\r)의 폭 계산을 어긋나게 한다.
    return " | ".join(parts)


def _char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def fit_width(text: str, width: int) -> str:
    """화면 폭 `width`칸에 맞춰 자르고 공백으로 채운다 — 한글은 2칸으로 센다.

    하트비트는 터미널에서 같은 줄을 `\\r`로 덮어쓰므로 매번 **정확히 같은 폭**이어야
    이전 줄의 꼬리가 남지 않는다. 폭을 넘으면 줄바꿈되어 `\\r`이 엉뚱한 줄을 덮는다.
    """
    out: list[str] = []
    used = 0
    for ch in text:
        w = _char_width(ch)
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out) + " " * (width - used)


def snapshot_to_dict(snap: Snapshot) -> dict:
    data = asdict(snap)
    data["prs"]["landed"] = {str(k): v for k, v in snap.prs.landed.items()}
    data["exit_code"] = exit_code(snap.signals)
    return data


def watch(
    root: Path,
    opts: Options,
    *,
    trunk_ref: str,
    interval: float,
    slow_interval: float,
    out: TextIO,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    clock: Callable[[], str] = _clock,
    max_cycles: int | None = None,
) -> int:
    """실시간 감시 루프 — 첫 주기는 전체 보고서, 이후는 달라진 것만 한 줄씩.

    변화가 없으면 하트비트 한 줄을 낸다. 터미널이면 같은 줄을 덮어써서(`\\r`) 화면이
    하트비트로 밀려나지 않게 하고, 파일·파이프면 줄마다 남긴다(나중에 읽을 기록이므로).
    미측정이 있는 주기는 하트비트가 아니라 **실패 줄**을 낸다 — "변화 없음"으로 보이면
    측정 실패가 정상으로 위장된다(③).
    """
    prev: Snapshot | None = None
    last_fetch_ok: float | None = None
    last_slow: float | None = None
    cycles = 0
    pending_heartbeat = False
    is_tty = bool(getattr(out, "isatty", lambda: False)())
    try:
        while True:
            started = now()
            slow = last_slow is None or started - last_slow >= slow_interval
            try:
                snap = take_snapshot(
                    root,
                    opts,
                    trunk_ref=trunk_ref,
                    prev=prev,
                    slow=slow,
                    last_fetch_ok=last_fetch_ok,
                )
            except Exception as exc:  # noqa: BLE001 — 한 주기의 내부 오류로 감시를 죽이지 않는다
                # 트레이스백으로 죽으면 종료 코드 1(= '주의 필요'와 같은 값)이 되고 감시가
                # 멈춘 줄도 모른다. 이 주기를 '미측정'으로 크게 알리고 다음 주기를 계속 돈다.
                if pending_heartbeat:
                    out.write("\n")
                    pending_heartbeat = False
                out.write(f"[{clock()}] [미측정] 감시기 내부 오류 — {type(exc).__name__}: {exc}\n")
                out.flush()
                last_code = EXIT_UNMEASURED
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    return last_code
                sleep(interval)
                continue
            if snap.local.fetch_state == "ok":
                last_fetch_ok = started
            if slow:
                last_slow = started
            if prev is None:
                out.write(render_report(snap) + "\n")
                out.write(
                    f"감시 시작 — main·체크아웃은 {interval:g}초마다, 열린 PR·원격 브랜치는 "
                    f"{slow_interval:g}초마다 다시 본다. 달라진 것만 [변화]/[주의] 줄로 알린다. "
                    "끝내려면 Ctrl+C\n"
                )
            else:
                events = diff_events(prev, snap)
                # 이번 주기에 **실제로 재려다 실패한** 신호만 실패 줄로 낸다. PR·원격 브랜치
                # 축은 느린 주기에만 다시 재므로, 그 사이 이어지는 '미측정'을 매분 되풀이하면
                # 같은 경고가 벽지가 된다(습관화 — CLAUDE.md 상시 실패 fail-open 항목).
                # 이어지는 상태는 하트비트 끝의 '미측정 N'이 계속 말한다.
                unmeasured = [
                    s
                    for s in snap.signals
                    if s.state == UNMEASURED and (slow or s.key not in SLOW_SIGNAL_KEYS)
                ]
                if events or unmeasured:
                    if pending_heartbeat:
                        out.write("\n")
                        pending_heartbeat = False
                    stamp = clock()
                    for event in events:
                        out.write(render_event(event, stamp) + "\n")
                    if unmeasured:
                        out.write(render_unmeasured(unmeasured, stamp) + "\n")
                elif is_tty:
                    out.write("\r" + fit_width(render_heartbeat(snap, clock()), HEARTBEAT_WIDTH))
                    pending_heartbeat = True
                else:
                    out.write(render_heartbeat(snap, clock()) + "\n")
            out.flush()
            prev = snap
            last_code = exit_code(snap.signals)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                if pending_heartbeat:
                    out.write("\n")  # 덮어쓰던 하트비트 줄을 닫는다 — 뒤 출력이 이어 붙지 않게
                    out.flush()
                return last_code
            sleep(interval)
    except KeyboardInterrupt:
        if pending_heartbeat:
            out.write("\n")
        out.write("감시 종료(Ctrl+C)\n")
        out.flush()
        return EXIT_OK


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


class _Parser(argparse.ArgumentParser):
    """인자 오류를 종료 코드 3으로 — argparse 기본값 2는 이 도구에서 '측정 실패'다."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: 인자 오류: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="main_watch.py",
        description="main 낡음·미머지 작업 점검 — 1회 점검 또는 실시간 감시 (HARN-176)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="실시간 감시 — 주기적으로 다시 재고 달라진 것만 알린다(Ctrl+C로 종료)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"main·체크아웃 확인 주기(초, 최소 {MIN_INTERVAL}) — 기본 %(default)s",
    )
    parser.add_argument(
        "--slow-interval",
        type=int,
        default=DEFAULT_SLOW_INTERVAL,
        help=f"열린 PR·원격 브랜치 확인 주기(초, 최소 {MIN_SLOW_INTERVAL}) — 기본 %(default)s",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="감시할 저장소 폴더 — 기본: 지금 폴더가 속한 저장소",
    )
    parser.add_argument(
        "--repo",
        default="",
        help="GitHub 저장소 owner/name — 기본: origin 주소에서 읽는다",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="원격을 새로 받지 않는다(이미 받아 둔 원격 ref로만 판정)",
    )
    parser.add_argument(
        "--max-ref-age",
        type=int,
        default=DEFAULT_MAX_REF_AGE_MIN,
        help="--no-fetch일 때 믿을 수 있는 원격 ref 나이 상한(분) — 기본 %(default)s",
    )
    parser.add_argument(
        "--skip",
        action="append",
        choices=AXES,
        default=[],
        help="건너뛸 축(반복 가능): prs=열린 PR, branches=오래된 원격 브랜치",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=remote_claims.STALE_BRANCH_DEFAULT_DAYS,
        help="원격 브랜치를 '오래 머지 안 됨'으로 볼 기준(일) — 기본 %(default)s",
    )
    parser.add_argument(
        "--no-gh",
        action="store_true",
        help="gh CLI에서 토큰을 빌리지 않는다(GITHUB_TOKEN·GH_TOKEN만 쓴다)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="1회 점검 결과를 JSON으로 낸다(--watch와 함께 쓸 수 없다)",
    )
    # 테스트 전용 — 감시 루프를 N주기 뒤 끝낸다(사람용 도움말에는 숨긴다).
    parser.add_argument("--max-cycles", type=int, default=None, help=argparse.SUPPRESS)
    return parser


def _resolve_root(given: Path | None) -> tuple[Path | None, str]:
    """감시할 저장소 루트와, 못 찾았다면 그 사유 — '저장소 아님'과 'git 미설치'를 가른다."""
    base = (given or Path.cwd()).expanduser()
    try:
        top = _git_out(base.resolve(), "rev-parse", "--show-toplevel").strip()
    except (GitQueryError, OSError) as exc:
        return None, str(exc)
    return (Path(top), "") if top else (None, "git rev-parse가 빈 경로를 냈다")


def _safe_stdio() -> None:
    """표준출력이 cp949 파일·파이프여도 죽지 않게 한다(⑤) — 못 쓰는 글자는 '?'로 바꾼다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError) as exc:
            print(f"경고: 출력 인코딩 설정 실패({type(exc).__name__})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    _safe_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.watch and args.json:
        parser.error("--json은 1회 점검 전용이다(--watch와 함께 쓸 수 없다)")
    if args.interval < MIN_INTERVAL:
        parser.error(f"--interval은 {MIN_INTERVAL}초 이상이어야 한다")
    if args.slow_interval < MIN_SLOW_INTERVAL:
        parser.error(f"--slow-interval은 {MIN_SLOW_INTERVAL}초 이상이어야 한다")
    if args.stale_days < 0 or args.max_ref_age < 1:
        parser.error("--stale-days는 0 이상, --max-ref-age는 1 이상이어야 한다")
    root, reason = _resolve_root(args.repo_root)
    if root is None:
        where = args.repo_root or Path.cwd()
        print(f"git 저장소를 찾지 못했다: {where} — {reason}", file=sys.stderr)
        return EXIT_USAGE

    skip = frozenset(args.skip)
    token_source, token_note = ("", "생략")
    if not skip.issuperset(AXES):
        token_source, token_note = resolve_token(use_gh=not args.no_gh)
    opts = Options(
        fetch=not args.no_fetch,
        skip=skip,
        stale_days=args.stale_days,
        max_ref_age_min=args.max_ref_age,
        repo_slug=args.repo or repo_slug_from_origin(root),
        token_source=token_source,
        token_note=token_note,
    )
    # 트렁크 이름은 원격에 한 번 묻는다(오프라인이면 'main'으로 폴백 — HARN-07 선례).
    trunk_ref, _ = remote_claims._resolve_trunk_ref(root)

    if args.watch:
        return watch(
            root,
            opts,
            trunk_ref=trunk_ref,
            interval=args.interval,
            slow_interval=args.slow_interval,
            out=sys.stdout,
            max_cycles=args.max_cycles,
        )
    try:
        snap = take_snapshot(root, opts, trunk_ref=trunk_ref)
    except Exception as exc:  # noqa: BLE001 — 내부 오류는 '측정 실패'다
        # 트레이스백으로 끝나면 종료 코드가 1이 되어 '주의 필요'와 구별되지 않는다.
        print(f"측정 실패 — 감시기 내부 오류({type(exc).__name__}: {exc})", file=sys.stderr)
        return EXIT_UNMEASURED
    if args.json:
        print(json.dumps(snapshot_to_dict(snap), ensure_ascii=True, indent=2))
    else:
        print(render_report(snap))
    return exit_code(snap.signals)


if __name__ == "__main__":
    raise SystemExit(main())
