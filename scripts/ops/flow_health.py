#!/usr/bin/env python3
"""통합 흐름 건강 진단 (Integration Flow Health) — FLOW-HEALTH.

**무엇을 재는가**: "코드는 작성됐는데 트렁크에 들어가지 못하는 상태"를 만드는
5개 신호를 원격 브랜치 전수에서 측정한다. 분류 코드는 GitHub 방해요인 taxonomy를
따른다(GIT-01 · GIT-04 · PR-03 · PR-04 · FLOW-01).

왜 이 도구가 필요한가 (2026-09-01 실측 근거)
--------------------------------------------
이 저장소에는 이미 인접 도구가 있지만 **재는 축이 다르다**:

  · `backlog.py branches`(HARN-47) — 브랜치의 *나이*와 *ahead*를 잰다. 소유자
    판정(고립/PR제출/진행중/포팅됨)이 목적이다.
  · `pr_delivery_audit.py`(HARN-30) — 열린 PR의 *체크런 배송 상태*를 잰다.
  · `pr_merge_readiness.py`(HARN-32) — 한 PR의 *머지 가능 시점*을 잰다.

**셋 중 어느 것도 `behind`(트렁크 대비 뒤처짐)를 재지 않는다.** `StaleBranch`는
`ahead`만 들고 있다. 그래서 브랜치 표류(GIT-01)는 이 저장소에서 **한 번도 측정된
적이 없는 축**이었고, 실측하니 17개 브랜치가 trunk 대비 124~247커밋 뒤처져 있었다.
같은 이유로 머지 충돌(GIT-04)도 무측정이었고, 실측하니 **열린 PR 15건 중 7건이
이미 main과 충돌 상태**였다 — 아무도 그 사실을 모르는 채로.

이 도구는 그 빈 축만 채운다. 겹치는 축(소유자 판정·체크런 배송)은 재구현하지
않는다 — 중복 구현은 이 저장소가 반복해서 겪은 실패다(ARCH-04).

설계 계약 (CLAUDE.md 준수)
--------------------------
① **측정 실패 ≠ 통과**: shallow·git 부재·merge-tree 미지원은 exit 2이며, 각 신호는
   `UNMEASURED`를 낼 수 있다. 빈 결과를 "이상 없음"으로 읽을 수 없게 만든다.
② **침묵 실패 금지**: 모든 실패 사유에 **예외 타입명**을 담는다.
③ **실패해도 증거가 남는다**: `--jsonl`을 주면 브랜치 1건을 잴 때마다 즉시 flush한다.
   중간에 죽어도 그 시점까지의 측정이 남는다.
④ **모든 서브프로세스에 타임아웃**을 건다.
⑤ **판정은 exit code**로 한다 — 출력 문자열 매칭이 아니다.
⑥ **인증 비의존**: 판정 핵심은 순수 git이다. `refs/pull/*/head`는 토큰 없이
   ls-remote로 읽힌다(`remote_claims._fetch_pr_head_shas` 선례와 같은 근거).
   PR 조회가 실패해도 드리프트·충돌 측정은 그대로 성립한다.

exit code
    0 — 차단 신호 없음(측정은 성공)
    1 — 차단 신호 있음
    2 — 측정 자체가 불가 (shallow·git 오류) — "이상 없음"으로 읽지 말 것
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ── 임계값 ────────────────────────────────────────────────────────────────
# 근거: 2026-09-01 실측 분포. behind 중앙값은 활성 브랜치(0~7)와 표류 브랜치
# (124~247) 사이가 완전히 비어 있다 — 그 골짜기에 선을 긋는다.
DRIFT_BEHIND = 50  # GIT-01: trunk 대비 이만큼 뒤처지면 표류
DRIFT_AGE_DAYS = 14  # GIT-01: 마지막 커밋 이후 경과일
OVERSIZED_FILES = 60  # PR-03: 변경 파일 수 — 리뷰 가능 상한
OVERLAP_FILES = 10  # PR-04: 브랜치 간 공유 파일 수 — 의존/중복 의심
WIP_BRANCHES = 12  # FLOW-01: PR 없는 in-flight 브랜치 수 상한

GIT_TIMEOUT = 60  # 모든 git 호출 공통 타임아웃 (④)
_API = "https://api.github.com"
_CA_PATH = "/root/.ccr/ca-bundle.crt"  # 에이전트 프록시 CA (있을 때만 사용)

# 감사 대상이 아닌 ref — 하네스 소유이거나 트렁크 자신.
EXCLUDED = frozenset({"main", "HEAD", "harness-claims"})

# 신호 코드 → 사람이 읽는 처방. 코드마다 처방이 **달라야** 한다 —
# 같은 처방을 내는 두 신호는 분리할 이유가 없다(test가 이것을 동결한다).
PRESCRIPTION = {
    "GIT-01": "트렁크를 브랜치에 머지해 표류를 좁히거나, 폐기 판정을 내린다",
    "GIT-04": "지금 충돌을 해소한다 — 시간이 갈수록 해소 비용은 단조 증가한다",
    "PR-03": "PR을 쪼갠다 — 리뷰 지연의 최대 단일 원인이다",
    "PR-04": "머지 순서를 정하거나 중복 구현 여부를 판정한다",
    "FLOW-01": "PR 미제출 브랜치를 제출·폐기 중 하나로 처분한다",
}

# 측정 불가를 표현하는 센티널. `0`(충돌 없음)과 **절대로 같은 값이면 안 된다** —
# 측정 실패와 통과가 같은 색이면 안 된다(①).
UNMEASURED = -1


def _auth_args() -> list[str]:
    """토큰이 있으면 `["-H", "Authorization: Bearer <token>"]`, 없으면 `[]`.

    **왜 필수인가** (2026-09-01 main red 2회차 실측): GitHub API의 **미인증** 한도는
    IP당 60req/h인데 러너는 IP를 공유하므로 실질 상시 소진이다
    (`API rate limit exceeded for 52.157.2.240`). 토큰이 없으면 이 도구는
    PR-03·FLOW-01을 영구 미측정으로 내며, 그것은 "상시 실패하는 fail-open 보호"가
    되는 경로다. 토큰이 없어도 조회는 시도하고, 실패는 미측정으로 **정직하게**
    보고된다(빈 Bearer를 보내지는 않는다).

    같은 형태를 `pr_delivery_audit.py`·`pr_merge_readiness.py`·
    `measure_merge_gate_latency.py`도 쓴다 — `tests/infra/test_github_api_auth.py`가
    네 파일 전부에서 이 헬퍼가 **실제 curl 인자에 실리는지** 동결한다.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return ["-H", f"Authorization: Bearer {token}"] if token else []


def _ca_args() -> list[str]:
    """프록시 CA를 쓸 수 있으면 `["--cacert", <경로>]`, 아니면 `[]`.

    **왜 존재 검사를 예외로 감싸는가** (2026-09-01 main red 실측): 초판은
    `Path(_CA).exists()`로 가드했는데, `Path.exists()`는 실패를 False로 돌려주지
    **않는다** — `pathlib._IGNORED_ERRNOS`는 `(ENOENT, ENOTDIR, EBADF, ELOOP)`뿐이라
    **EACCES는 전파된다**. GitHub 러너의 `runner` 유저는 `/root`(mode 700)를 통과할
    수 없으므로 가드 자체가 `PermissionError`로 죽어 잡이 통째로 실패했다.
    "없으면 건너뛴다"는 의도였는데 "없으면 터진다"가 된 것이다.

    이 경로는 에이전트 프록시가 있는 실행 환경에만 존재하므로, 없으면 시스템
    신뢰저장소를 쓰는 것이 정상 동작이다.
    """
    try:
        with open(_CA_PATH, "rb"):  # 존재 + 읽기 권한을 한 번에 확인한다
            return ["--cacert", _CA_PATH]
    except OSError:
        return []


@dataclass
class BranchFlow:
    """원격 브랜치 1건의 통합 흐름 측정치."""

    branch: str
    ahead: int
    behind: int
    age_days: float
    files: int
    # 트렁크와의 실제 머지 충돌 파일 수. UNMEASURED(-1)이면 재지 못한 것이다.
    conflicts: int = UNMEASURED
    # 이 tip으로 PR이 **제출된 적이 있는가**(git ls-remote refs/pull/*/head).
    # 열려 있다는 뜻이 **아니다** — 닫힌 PR도 여기 잡힌다(실측: PR #675는
    # closed·unmerged인데 tip이 일치했다).
    pr_ref: int | None = None
    # 그 PR이 **지금 열려 있는가**. None = 미판정(API 조회 실패) — False와 다르다.
    pr_open: bool | None = None
    active: bool = False  # 다른 세션이 claim 중


@dataclass
class Finding:
    code: str
    subject: str
    detail: str
    prescription: str = ""

    def __post_init__(self) -> None:
        self.prescription = PRESCRIPTION.get(self.code, "")


@dataclass
class Report:
    status: str  # ok | shallow | error
    findings: list[Finding] = field(default_factory=list)
    branches: list[BranchFlow] = field(default_factory=list)
    message: str = ""
    # 측정하지 못한 축 — 비어 있지 않으면 이 리포트는 부분 측정이다.
    unmeasured: list[str] = field(default_factory=list)


# ── 순수 판정 로직 (git 없이 테스트 가능) ──────────────────────────────────
def classify(
    branches: list[BranchFlow],
    overlaps: list[tuple[str, str, int]],
    *,
    drift_behind: int = DRIFT_BEHIND,
    drift_age_days: int = DRIFT_AGE_DAYS,
    oversized_files: int = OVERSIZED_FILES,
    overlap_files: int = OVERLAP_FILES,
    wip_branches: int = WIP_BRANCHES,
) -> list[Finding]:
    """측정치 → 신호 목록. **순수 함수** — I/O 없음.

    판정을 git 호출에서 분리한 이유: 네트워크·저장소 상태 없이 임계 동작을
    양방향으로 동결할 수 있어야 한다(정상 상태에서 침묵하고 결함 상태에서
    발화하는지 — "변별력 없는 검증 스텝 금지").
    """
    findings: list[Finding] = []

    # 진행 중(active) 브랜치는 방치가 아니다 — 표류·WIP 판정에서 제외한다.
    # 이 제외를 빠뜨리면 "지금 작업 중인 브랜치"가 경고로 뜬다(HARN-47이 겪은
    # 오경보 형태). 단 충돌(GIT-04)은 active여도 낸다 — 지금 고쳐야 할 사실이다.
    dormant = [b for b in branches if not b.active]

    # GIT-01 브랜치 표류 — behind AND age 둘 다 넘어야 한다.
    # behind만 보면 "오늘 만든 브랜치가 오래된 trunk에서 갈라져 나온" 정상 상태를
    # 표류로 오판한다.
    for b in sorted(dormant, key=lambda x: -x.behind):
        if b.behind >= drift_behind and b.age_days >= drift_age_days:
            findings.append(
                Finding(
                    "GIT-01",
                    b.branch,
                    f"trunk 대비 {b.behind}커밋 뒤처짐 · {b.age_days:.0f}일 방치 "
                    f"· 변경 {b.files}파일",
                )
            )

    # GIT-04 머지 충돌 — 이미 발생한 사실이다(예측이 아니다).
    # UNMEASURED(-1)를 "충돌 없음"으로 읽지 않도록 명시 비교한다.
    for b in sorted(branches, key=lambda x: -x.conflicts):
        if b.conflicts != UNMEASURED and b.conflicts > 0:
            if b.pr_open:
                where = f"PR #{b.pr_ref} (열림)"
            elif b.pr_ref:
                where = f"PR #{b.pr_ref} (닫힘·미머지)"
            else:
                where = "PR 미제출"
            findings.append(
                Finding("GIT-04", b.branch, f"main과 {b.conflicts}개 파일 충돌 · {where}")
            )

    # PR-03 과대 PR — **열려 있는** PR에만 적용한다. 닫힌 PR은 리뷰 부하가 아니다
    # (실측 교훈: PR ref 존재만으로 판정했더니 closed·unmerged인 #675가 잡혔다).
    # pr_open이 None(미판정)이면 발화하지 않는다 — 추측으로 신호를 만들지 않는다.
    for b in sorted(branches, key=lambda x: -x.files):
        if b.pr_open and b.files >= oversized_files:
            findings.append(
                Finding("PR-03", f"PR #{b.pr_ref}", f"{b.files}개 파일 변경 ({b.branch})")
            )

    # PR-04 브랜치 간 겹침 — 머지 순서 의존 또는 중복 구현의 신호.
    for a, c, n in sorted(overlaps, key=lambda x: -x[2]):
        if n >= overlap_files:
            findings.append(Finding("PR-04", f"{a} ↔ {c}", f"{n}개 파일을 공유한다"))

    # FLOW-01 과다 WIP — **열린 PR이 없는** 브랜치가 상한을 넘으면 개별이 아니라
    # 총량이 문제다. 그래서 브랜치별이 아니라 **1건**의 신호로 낸다.
    # 닫힌 PR을 가진 브랜치는 여기 포함된다 — 닫히고 머지 안 됐다는 것은 작업이
    # 트렁크 밖에 남았다는 뜻이므로, PR이 없는 것보다 더 방치된 상태다.
    # `is False`인 이유(Codex P2 지적): `not b.pr_open`은 `None`(열림 여부 **미판정**)
    # 까지 "PR 없음"으로 센다. API 장애·rate limit이면 전 브랜치가 미판정이 되므로
    # 순전히 모르는 데이터로 FLOW-01이 확정 발화한다 — collect()가 같은 상황을
    # unmeasured로 표시해 놓고 신호는 내는 자기모순이다. 아는 것만 센다.
    unfiled = [b for b in dormant if b.pr_open is False]
    if len(unfiled) > wip_branches:
        findings.append(
            Finding(
                "FLOW-01",
                f"{len(unfiled)}개 브랜치",
                f"PR 미제출 브랜치가 상한({wip_branches})을 초과했다",
            )
        )

    return findings


# ── git 수집 계층 ─────────────────────────────────────────────────────────
class GitError(RuntimeError):
    """git 호출 실패. 사유에 **예외 타입명**을 담아 전파한다(②)."""


def _git(root: Path, *args: str, timeout: int = GIT_TIMEOUT) -> str:
    """git 1회 호출. 실패는 삼키지 않고 타입명과 함께 올린다.

    `check=False` + 명시 판정을 쓴다 — `CalledProcessError`의 기본 메시지는
    stderr를 담지 않아, 실패 8종이 운영자에게 같은 글자로 보인다.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            # HARN-19 — 로케일 인코딩 디코드 금지. Kiki 머신(한국어 Windows)은
            # cp949라 한글 브랜치명·커밋 제목에서 붕괴한다. git 출력은 UTF-8이다.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,  # ④ 모든 외부 프로세스에 타임아웃
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"TimeoutExpired: git {args[0]} — {timeout}s 초과") from exc
    except OSError as exc:  # git 미설치·권한
        raise GitError(f"{type(exc).__name__}: {exc}") from exc
    if proc.returncode != 0:
        raise GitError(
            f"GitExitError({proc.returncode}): git {args[0]} — {proc.stderr.strip()[:200]}"
        )
    return proc.stdout


def _is_shallow(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-shallow-repository").strip() == "true"


def _conflict_count(root: Path, trunk: str, ref: str) -> int:
    """`ref`를 `trunk`에 머지하면 충돌하는 파일 수. 못 재면 UNMEASURED.

    `merge-tree --write-tree`는 **작업 트리를 건드리지 않는다** — 체크아웃도
    인덱스 변경도 없으므로 다른 세션의 작업 트리를 오염시키지 않는다.
    git 2.38+ 필요. 미지원이면 0이 아니라 UNMEASURED를 낸다(①).
    """
    try:
        proc = subprocess.run(
            ["git", "merge-tree", "--write-tree", "--name-only", trunk, ref],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",  # HARN-19
            errors="replace",
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return UNMEASURED
    # exit 0 = 충돌 없음, 1 = 충돌 있음, 그 외(128 등) = 측정 불가.
    if proc.returncode == 0:
        return 0
    if proc.returncode != 1:
        return UNMEASURED
    # 충돌 시 stdout = "<oid>\n<충돌 파일 목록>\n\n<메시지>". 첫 줄(트리 oid)을
    # 버리고 빈 줄 전까지가 파일 목록이다.
    lines = proc.stdout.splitlines()[1:]
    files = []
    for line in lines:
        if not line.strip():
            break
        files.append(line.strip())
    return len(files) or UNMEASURED


def _pr_head_map(root: Path) -> tuple[dict[str, int], str]:
    """`refs/pull/<N>/head` → {sha: PR번호}. 실패해도 전체 측정을 멈추지 않는다.

    토큰 없이 읽힌다(⑥). 실패 시 `({}, "<타입>: <상세>")`를 돌려주고 호출부가
    "PR 판정 미수행"을 리포트에 남긴다 — 조용히 "PR 없음"으로 만들지 않는다.
    """
    try:
        out = _git(root, "ls-remote", "origin", "refs/pull/*/head", timeout=30)
    except GitError as exc:
        return {}, str(exc)
    mapping: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        try:
            mapping[sha] = int(ref.split("/")[2])
        except (IndexError, ValueError):
            continue
    return mapping, ""


def _open_pr_numbers(root: Path) -> tuple[set[int] | None, str]:
    """지금 **열려 있는** PR 번호 집합. 실패 시 `(None, "<타입>: <상세>")`.

    왜 별도 조회인가: `refs/pull/<N>/head`는 PR이 **제출된 적 있음**만 증명한다.
    닫힌 PR도 tip이 일치하면 잡힌다(2026-09-01 실측: PR #675는 closed·unmerged인데
    브랜치 tip과 일치해 "PR 있음"으로 분류됐고, 그 결과 ①리뷰 부하가 없는 PR에
    PR-03이 발화하고 ②실제로는 트렁크 밖에 남은 작업이 WIP 집계에서 빠졌다).

    실패는 `None`이며 **빈 집합이 아니다** — 빈 집합으로 돌려주면 "열린 PR 0건"이
    되어 모든 브랜치가 방치로 보인다. 측정 실패와 통과는 같은 색이면 안 된다(①).
    """
    url = None
    try:
        remote = _git(root, "remote", "get-url", "origin", timeout=15).strip()
    except GitError as exc:
        return None, str(exc)
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote)
    if not m:
        return None, f"RemoteParseError: origin이 GitHub이 아니다({remote[:60]})"
    url = f"{_API}/repos/{m.group(1)}/{m.group(2)}/pulls?state=open&per_page=100"

    numbers: set[int] = set()
    for page in range(1, 6):  # 상한 500건 — 무한 페이징 금지
        cmd = [
            "curl",
            "-sS",
            "-L",  # 이관 리다이렉트 추종 — 301 본문을 데이터로 오독하지 않기 위해
            "--max-time",
            "30",
            *_ca_args(),
            *_auth_args(),
            "-H",
            "Accept: application/vnd.github+json",
            f"{url}&page={page}",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",  # HARN-19 — API 응답도 UTF-8이다
                errors="replace",
                timeout=40,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, f"{type(exc).__name__}: {exc}"
        if proc.returncode != 0:
            # ② 실패 원인을 남긴다 — stderr 없이 타입명만 남기면 8종이 같은 글자가 된다
            return None, f"CurlExitError({proc.returncode}): {proc.stderr.strip()[:160]}"
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return None, f"JSONDecodeError: {exc} — 본문 {proc.stdout[:120]!r}"
        if isinstance(data, dict):  # rate limit·404는 dict로 온다
            return None, f"APIError: {str(data.get('message'))[:120]}"
        if not data:
            break
        numbers.update(int(x["number"]) for x in data if "number" in x)
        if len(data) < 100:
            break
    return numbers, ""


def collect(
    root: Path,
    *,
    trunk: str = "origin/main",
    active_branches: frozenset[str] = frozenset(),
    jsonl: Path | None = None,
    measure_conflicts: bool = True,
) -> Report:
    """원격 브랜치를 전수 측정한다.

    `jsonl`이 주어지면 브랜치 1건마다 **즉시 flush**한다(③) — 도중에 죽어도
    그 시점까지의 측정이 파일에 남는다. 마지막에 한 번 저장하면 전부 잃는다.
    """
    try:
        if _is_shallow(root):
            # shallow에서 ahead/behind는 잘린 히스토리 기준이라 **틀린 수**가 나온다.
            # 틀린 수를 내느니 측정 불가를 선언한다.
            return Report(
                status="shallow",
                message="shallow 클론 — ahead/behind가 잘린 히스토리 기준이라 신뢰 불가. "
                "`git fetch --unshallow origin` 후 재실행",
                unmeasured=["GIT-01", "GIT-04", "PR-03", "PR-04", "FLOW-01"],
            )
        refs = _git(
            root,
            "for-each-ref",
            "--format=%(refname:short)%09%(committerdate:unix)",
            "refs/remotes/origin",
        )
    except GitError as exc:
        return Report(
            status="error",
            message=str(exc),
            unmeasured=["GIT-01", "GIT-04", "PR-03", "PR-04", "FLOW-01"],
        )

    pr_map, pr_err = _pr_head_map(root)
    report = Report(status="ok")
    notes: list[str] = []
    if pr_err:
        # PR ref 자체를 못 읽었다 — 모든 브랜치가 "PR 없음"으로 보인다.
        report.unmeasured.extend(["PR-03", "FLOW-01"])
        notes.append(f"PR ref 조회 실패({pr_err})")

    open_prs, open_err = (None, "") if pr_err else _open_pr_numbers(root)
    if open_err:
        # 열림 여부를 모른다 → PR-03은 발화하지 않고(추측 금지), FLOW-01은
        # 닫힌 PR을 열린 것으로 착각할 수 있다. 둘 다 미측정으로 표시한다.
        for code in ("PR-03", "FLOW-01"):
            if code not in report.unmeasured:
                report.unmeasured.append(code)
        notes.append(f"열린 PR 조회 실패({open_err})")
    if notes:
        report.message = " · ".join(notes) + " — PR-03·FLOW-01 미판정"

    now = datetime.now(timezone.utc)
    sink = jsonl.open("w", encoding="utf-8") if jsonl else None
    try:
        for line in refs.splitlines():
            if "\t" not in line:
                continue
            full, ts = line.split("\t", 1)
            name = full.removeprefix("origin/")
            if name in EXCLUDED:
                continue
            try:
                counts = _git(
                    root, "rev-list", "--left-right", "--count", f"{trunk}...{full}"
                ).split()
                behind, ahead = int(counts[0]), int(counts[1])
                if ahead == 0:
                    continue  # 트렁크에 흡수됨 — 흐름 문제가 아니다
                files = len(_git(root, "diff", "--name-only", f"{trunk}...{full}").splitlines())
                sha = _git(root, "rev-parse", full).strip()
            except (GitError, ValueError, IndexError) as exc:
                # 브랜치 1건 실패가 전체 스캔을 죽이지 않는다. 다만 조용히 넘기지도
                # 않는다 — 사유를 타입명과 함께 남긴다(②).
                report.unmeasured.append(f"{name}({type(exc).__name__})")
                continue

            bf = BranchFlow(
                branch=name,
                ahead=ahead,
                behind=behind,
                age_days=(now.timestamp() - int(ts)) / 86400,
                files=files,
                conflicts=_conflict_count(root, trunk, full) if measure_conflicts else UNMEASURED,
                pr_ref=pr_map.get(sha),
                pr_open=(
                    None
                    if open_prs is None
                    else (pr_map.get(sha) in open_prs if pr_map.get(sha) else False)
                ),
                active=name in active_branches,
            )
            report.branches.append(bf)
            if sink:  # ③ 단계마다 즉시 flush
                sink.write(json.dumps(asdict(bf), ensure_ascii=False, default=str) + "\n")
                sink.flush()
    finally:
        if sink:
            sink.close()
    return report


def compute_overlaps(
    root: Path, branches: list[BranchFlow], *, trunk: str = "origin/main", top: int = 14
) -> list[tuple[str, str, int]]:
    """in-flight 브랜치 쌍의 공유 파일 수 (PR-04).

    O(n²) 비교이므로 최근 활동 상위 `top`개로 제한한다 — 표류 브랜치끼리의
    겹침은 처방이 같아서(폐기) 쌍으로 셀 실익이 없다.
    """
    live = sorted(branches, key=lambda b: b.age_days)[:top]
    filesets: dict[str, set[str]] = {}
    for b in live:
        try:
            out = _git(root, "diff", "--name-only", f"{trunk}...origin/{b.branch}")
        except GitError:
            continue
        filesets[b.branch] = set(out.splitlines())
    pairs: list[tuple[str, str, int]] = []
    names = sorted(filesets)
    for i, a in enumerate(names):
        for c in names[i + 1 :]:
            shared = len(filesets[a] & filesets[c])
            if shared:
                pairs.append((a, c, shared))
    return pairs


# ── CLI ───────────────────────────────────────────────────────────────────
def _active_branches(root: Path) -> tuple[frozenset[str], str]:
    """원격 claim 대장에서 '지금 작업 중인 브랜치'를 읽는다. `(브랜치집합, 사유)`.

    **조용히 빈 집합을 돌려주지 않는다** (Codex P2 지적, 2026-09-01). 초판은
    ⓐ `sys.path`에 `scripts`를 넣어(하네스 모듈은 서로를 top-level로 import하므로
    `scripts/harness`여야 한다) `ModuleNotFoundError`, ⓑ 존재하지 않는
    `load_remote_claim_map`을 호출해 `AttributeError`를 냈고, 광범위 `except`가
    **둘 다 삼켰다**. 결과는 무증상 오작동이다 — active 브랜치가 전부 dormant로
    분류돼 타 세션이 지금 작업 중인 브랜치에 GIT-01·FLOW-01 오경보가 난다
    (HARN-47이 없애려던 바로 그 오경보). 실측 시점에 claim 3건이 살아 있었는데
    이 함수는 `frozenset()`을 냈다.

    그래서 실패 사유를 **반환값으로 올린다** — 호출부가 리포트에 남긴다.
    `backlog.py:_remote_claim_map`과 같은 리더(`list_claims`)를 쓴다.
    """
    harness_dir = str(root / "scripts" / "harness")
    if harness_dir not in sys.path:
        sys.path.insert(0, harness_dir)
    try:
        import remote_claims  # noqa: PLC0415
        import store  # noqa: PLC0415
    except ImportError as exc:
        return frozenset(), f"{type(exc).__name__}: {exc}"
    try:
        policy, _ = store.load_policy(root)
        if not policy.remote_claims:
            return frozenset(), ""  # 기능 자체가 꺼져 있음 — 실패가 아니다
        claims, status = remote_claims.list_claims(root, with_meta=True)
    except Exception as exc:  # noqa: BLE001 - 환경 의존(네트워크·권한)
        return frozenset(), f"{type(exc).__name__}: {exc}"
    if status != "ok":
        # 조회 자체가 실패 — "active 0건"과 구분해서 올린다.
        return frozenset(), f"claim 조회 status={status}"
    return frozenset(c.branch for c in claims if getattr(c, "branch", None)), ""


def render(report: Report, findings: list[Finding], *, verbose: bool = False) -> str:
    out: list[str] = []
    if report.status != "ok":
        out.append(f"측정 불가: status={report.status} — {report.message}")
        return "\n".join(out)
    if report.message:
        out.append(f"⚠ {report.message}")

    measured = len(report.branches)
    conflicted = sum(1 for b in report.branches if b.conflicts > 0)
    # 요약은 classify와 **같은 조건**을 써야 한다(Codex P2 지적) — behind만 보면
    # 오래된 trunk에서 오늘 갈라진 브랜치가 요약에서는 표류로 세어지는데 상세에는
    # GIT-01이 안 뜬다. 첫 줄 합계가 아래 진단과 모순되는 상태가 된다.
    drifted = sum(
        1
        for b in report.branches
        if b.behind >= DRIFT_BEHIND and b.age_days >= DRIFT_AGE_DAYS and not b.active
    )
    unfiled = sum(1 for b in report.branches if b.pr_open is False and not b.active)
    out.append(
        f"브랜치 {measured}건 측정 · 충돌 {conflicted}건 · 표류 {drifted}건 · PR미제출 {unfiled}건"
    )

    by_code: dict[str, list[Finding]] = {}
    for f in findings:
        by_code.setdefault(f.code, []).append(f)
    for code in sorted(by_code):
        items = by_code[code]
        out.append(f"\n[{code}] {len(items)}건 — {PRESCRIPTION[code]}")
        shown = items if verbose else items[:6]
        for f in shown:
            out.append(f"  · {f.subject}: {f.detail}")
        if len(items) > len(shown):
            out.append(f"  … 외 {len(items) - len(shown)}건 (--verbose로 전체)")

    if report.unmeasured:
        # 부분 측정임을 반드시 말한다 — 침묵하면 "전부 쟀다"로 읽힌다(①).
        out.append(f"\n⚠ 미측정 축 {len(report.unmeasured)}건: {', '.join(report.unmeasured[:8])}")
    if not findings:
        out.append("\n차단 신호 없음.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="통합 흐름 건강 진단 (FLOW-HEALTH)")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--trunk", default="origin/main")
    p.add_argument("--json", action="store_true", help="기계 판독 출력")
    p.add_argument("--jsonl", type=Path, help="브랜치별 측정을 즉시 flush할 경로")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--no-conflicts", action="store_true", help="충돌 측정 생략(빠른 스캔)")
    p.add_argument(
        "--warn-only",
        action="store_true",
        help="신호가 있어도 exit 0 — 관측 전용(무관한 PR을 red로 만들지 않는다)",
    )
    p.add_argument("--drift-behind", type=int, default=DRIFT_BEHIND)
    p.add_argument("--drift-age-days", type=int, default=DRIFT_AGE_DAYS)
    p.add_argument("--oversized-files", type=int, default=OVERSIZED_FILES)
    p.add_argument("--overlap-files", type=int, default=OVERLAP_FILES)
    p.add_argument("--wip-branches", type=int, default=WIP_BRANCHES)
    args = p.parse_args(argv)

    active, claim_err = _active_branches(args.root)
    report = collect(
        args.root,
        trunk=args.trunk,
        active_branches=active,
        jsonl=args.jsonl,
        measure_conflicts=not args.no_conflicts,
    )
    if claim_err:
        # active를 못 읽었으면 진행 중 브랜치가 표류·WIP로 오분류된다. 침묵 금지.
        report.unmeasured.append(f"active판정({claim_err})")
    if report.status != "ok":
        print(render(report, []))
        return 2  # 측정 실패는 통과(0)도 신호(1)도 아니다 — 세 번째 색이다

    overlaps = compute_overlaps(args.root, report.branches, trunk=args.trunk)
    findings = classify(
        report.branches,
        overlaps,
        drift_behind=args.drift_behind,
        drift_age_days=args.drift_age_days,
        oversized_files=args.oversized_files,
        overlap_files=args.overlap_files,
        wip_branches=args.wip_branches,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "status": report.status,
                    "unmeasured": report.unmeasured,
                    "findings": [asdict(f) for f in findings],
                    "branches": [asdict(b) for b in report.branches],
                },
                ensure_ascii=False,
                default=str,
                indent=2,
            )
        )
    else:
        print(render(report, findings, verbose=args.verbose))
    if args.warn_only:
        return 0
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
