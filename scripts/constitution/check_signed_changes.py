#!/usr/bin/env python3
"""scripts/constitution/check_signed_changes.py — 헌법 밖 경로 보호 (CONST-17 · 제9조 ① 집행의 2층).

가드 훅(`.claude/hooks/guard_constitution.py`)은 Claude Code 도구 호출만 본다. 같은 신원(사람과
AI 세션이 한 GitHub 계정)이라 GitHub 쪽에서는 "누가 고쳤나"를 구별하지 못한다. 그래서 **서명**으로
구별한다: Kiki 만 가진 SSH 서명 키로 서명된 커밋만 보호 경로를 바꿀 수 있다. AI 세션은 키가
없어 어떤 경로(웹 UI·API·훅 밖 스크립트)로 올려도 서명할 수 없다.

무엇을 보호하나 (보호 경로를 바꾼 커밋은 *모두* 서명돼야 한다)
  · `constitution/` 전체 — 헌법 본문·규칙 등록부·단계·개정 기록·판례
  · `constitution_signers/` — 서명자 공개키 목록(`allowed_signers`)
  · 이 스크립트 자신 — 검증기를 고쳐 통과시키는 길을 막는다
  · `.github/workflows/ci.yml` 의 **검증 스텝과 잡 게이팅 사실**(on·잡의 if·continue-on-error·
    needs·runs-on·env·permissions·defaults·container·services + 검증 스텝 정의 전체).
    경로 전체를 묶지 않는 이유: ci.yml 은 다른 PR 이 자주 고친다 — 통째로 묶으면 AI 의 모든 CI
    수정이 막혀 사람이 장치를 끈다. 사실이 같으면(다른 스텝 편집) 서명이 필요 없다.

핵심 설계 결정
  ① **서명자 목록은 기준(base) 트리에서 읽는다 — PR 헤드가 아니다.** PR 이 자기 키를 목록에 넣고
     그 키로 서명해 스스로 통과하는 길을 막는다. 키 교체도 *기존* 키의 서명이 있어야 한다.
  ② **`G`(좋은 서명, 허용 목록에 있는 키)만 통과다.** `U`(서명은 유효하나 목록에 없는 키)·`N`(서명
     없음)·`B`(손상)·`E`(검증 불가)·`X`·`Y`·`R` 은 전부 실패다. 허용 파일이 없거나 비어도
     git 은 `G` 를 내지 않고 `U` 를 낸다(2026-10-16 실측) — 그래서 `G` 하나만 믿으면
     fail-open 이 생기지 않는다.
  ③ **범위는 `base..head` 의 모든 커밋이다.** 보호 경로를 바꾼 커밋마다 따로 본다 — 서명된 커밋
     뒤에 서명 없는 커밋이 되돌리거나 덧써도 잡힌다. 병합 커밋은 모든 부모와 다른 파일(결합 diff,
     충돌 해소로 끼어든 변경)만 본다: 깨끗한 병합은 main 쪽 변경을 이 PR 탓으로 돌리지 않는다.
  ④ **PR 이벤트에서만 판정한다.** 머지 큐(`merge_group`)의 스쿼시 커밋은 GitHub 서명이라 Kiki 키가
     아니다 — 그 변경은 PR 시점에 이미 이 검사를 통과해야만 큐에 들어온다. 로컬 실행(이벤트 없음)은
     판정한다.
  ⑤ **미무장(unarmed)은 명시적 상태다.** 기준 트리에 서명자 목록 파일이 *없으면* 아직 키가 등록되지
     않은 것이다 — 부트스트랩이라 통과(exit 0)하되 크게 알린다. 키 등록 PR(= 목록 파일을 처음
     만드는 커밋)은 Kiki 가 직접 서명해 올린다(런북 `docs/ops/constitution_signing_runbook.md`).
     파일이 *있는데* 유효한 키가 하나도 없으면 미무장이 아니라 **측정 불가(exit 2)** 다 — 빈 파일로
     검사를 끄는 길을 막는다. 무장 시점의 재확인은 게이트 `G-const-signing-key-register` 가 맡는다.

종료 코드: 0 통과(변경 없음·전부 서명됨·미무장·판정 제외 이벤트) / 1 위반 / 2 측정 불가
  측정 불가(ref 없음·git 실패·ssh-keygen 없음·서명자 목록 해석 불가)를 통과로 돌리지 않는다.

한계(명시 — 막지 못하는 것을 막는다고 말하지 않는다)
  · ci.yml 의 *다른* 스텝 조작(예: 앞 스텝이 환경변수로 이벤트를 위장)은 이 검사가 막지 못한다.
  · 미무장 동안은 아무것도 강제되지 않는다. 키 등록 PR 을 AI 가 올리고 사람이 내용을 안 보고
    승인하면 AI 키가 등록된다 — 등록 PR 은 Kiki 가 직접 만든다.
  · 저장소 설정(룰셋의 필수 체크 목록)은 이 스크립트 밖이다. 이 체크를 포함한 잡이 필수 체크가
    아니면 빨간불이 병합을 막지 못한다.
  · 이 스크립트는 다른 헌법 스크립트(check_amendment.py)를 import 하지 않는다 — 보호 대상인
    검증기가 보호받지 않는 파일에 의존하면 그 파일을 고쳐 검증을 바꿀 수 있다.

사용: python scripts/constitution/check_signed_changes.py [--base REF] [--head REF] [--repo DIR]
  --base 기본값: 환경변수 CONSTITUTION_BASE_REF, 없으면 origin/main
  --event 기본값: 환경변수 GITHUB_EVENT_NAME (없으면 로컬 실행 = 판정)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 윈도우 콘솔(cp949)에서 한글이 깨져 스크립트가 죽지 않도록 UTF-8로 출력
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[2]

#: 서명자 목록 — 기준 트리에서 읽는다(PR 헤드가 아니다)
SIGNERS_PATH = "constitution_signers/allowed_signers"
#: 보호 디렉터리 (끝에 / 포함 — 접두 비교)
PROTECTED_DIRS: tuple[str, ...] = ("constitution/", "constitution_signers/")
#: 보호 파일 (이 검증기 자신)
PROTECTED_FILES: tuple[str, ...] = ("scripts/constitution/check_signed_changes.py",)
#: 워크플로 — 경로 전체가 아니라 검증 스텝·게이팅 사실만 묶는다
WORKFLOW_PATH = ".github/workflows/ci.yml"
VERIFIER_JOB = "harness-integrity"
VERIFIER_MARK = "check_signed_changes.py"
#: 잡 게이팅 사실로 보는 키 — 하나라도 달라지면 검증이 꺼지거나 우회될 수 있다
JOB_FACT_KEYS: tuple[str, ...] = (
    "if",
    "continue-on-error",
    "needs",
    "runs-on",
    "env",
    "defaults",
    "container",
    "services",
    "permissions",
    "strategy",
)
WORKFLOW_FACT_KEYS: tuple[str, ...] = ("env", "defaults", "permissions", "concurrency")
#: 판정하는 이벤트 — 빈 값(로컬 실행)과 pull_request. 나머지는 PR 시점에 이미 검증된 변경이다
VERIFY_EVENTS: frozenset[str] = frozenset({"", "pull_request"})
GIT_TIMEOUT_SEC = 60
#: `git log %G?` 의 좋은 서명 코드 — 이것만 통과다
GOOD_SIGNATURE = "G"
KEY_TYPE_PREFIXES = ("ssh-", "ecdsa-", "sk-")


class MeasureError(Exception):
    """측정 불가 — 호출자가 종료 코드 2 로 바꾼다(통과로 위장하지 않는다)."""


@dataclass(frozen=True)
class Verdict:
    sha: str
    subject: str
    reasons: tuple[str, ...]  # 이 커밋이 서명돼야 하는 이유(바꾼 보호 경로 등)
    status: str  # %G? 코드
    fingerprint: str
    principal: str

    @property
    def ok(self) -> bool:
        return self.status == GOOD_SIGNATURE


# ─────────────────────────── git 입출력 ───────────────────────────
def git(repo: Path, *args: str, config: tuple[str, ...] = ()) -> bytes:
    cmd = ["git", "-C", str(repo)]
    for item in config:
        cmd += ["-c", item]
    try:
        proc = subprocess.run(
            [*cmd, *args], capture_output=True, timeout=GIT_TIMEOUT_SEC, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MeasureError(f"git 실행 실패({type(exc).__name__}): {' '.join(args)}") from exc
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace").strip()[-300:]
        raise MeasureError(f"git {' '.join(args)} 실패(exit {proc.returncode}): {tail}")
    return proc.stdout


def decode(raw: bytes, what: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MeasureError(f"{what} 을 UTF-8 로 읽지 못함({type(exc).__name__})") from exc


def rev(repo: Path, ref: str) -> str:
    try:
        out = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except MeasureError as exc:
        raise MeasureError(
            f"ref 를 찾지 못함({ref}) — CI 라면 checkout 의 fetch-depth: 0 이 필요하다: {exc}"
        ) from exc
    return decode(out, ref).strip()


# ─────────────────────────── 보호 경로 판정 ───────────────────────────
def is_protected_path(path: str) -> bool:
    return path.startswith(PROTECTED_DIRS) or path in PROTECTED_FILES


def _split_z(raw: bytes, what: str) -> list[str]:
    parts = decode(raw, what).split("\0")
    return [p for p in parts if p]


def changed_paths(repo: Path, sha: str, parents: list[str]) -> list[str]:
    """커밋이 바꾼 파일. 병합은 모든 부모와 다른 파일만(결합 diff) — 깨끗한 병합은 비어 있다."""
    if len(parents) > 1:
        raw = git(repo, "diff-tree", "--cc", "-r", "--name-only", "-z", "--no-commit-id", sha)
    else:
        raw = git(
            repo, "diff-tree", "-r", "--no-renames", "--root", "--name-only", "-z",
            "--no-commit-id", sha,
        )  # fmt: skip
    return _split_z(raw, f"{sha[:8]} 변경 목록")


def _blob(repo: Path, ref: str, path: str) -> str | None:
    """ref 의 트리에서 파일을 읽는다. 없으면 None."""
    listing = git(repo, "ls-tree", "-z", ref, "--", path)
    if not listing.strip(b"\0"):
        return None
    return decode(git(repo, "show", f"{ref}:{path}"), f"{ref}:{path}")


def workflow_facts(text: str | None) -> Any:
    """ci.yml 에서 검증이 꺼지거나 우회될 수 있는 사실만 뽑는다. 해석 불가면 ValueError."""
    if text is None:
        return {"present": False}
    try:
        import yaml  # 지연 임포트 — 하네스 잡에는 PyYAML 이 있다
    except ImportError as exc:  # pragma: no cover - 환경 문제는 측정 불가로 올린다
        raise MeasureError(f"PyYAML 을 불러오지 못함({type(exc).__name__})") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"ci.yml 해석 실패({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("ci.yml 최상위가 사전이 아님")
    # PyYAML 은 키 `on` 을 불리언 True 로 읽는다(YAML 1.1)
    trigger = data["on"] if "on" in data else data.get(True)
    job = (data.get("jobs") or {}).get(VERIFIER_JOB)
    step = None
    if isinstance(job, dict):
        for item in job.get("steps") or []:
            if isinstance(item, dict) and VERIFIER_MARK in str(item.get("run", "")):
                step = item
                break
    return {
        "present": True,
        "on": trigger,
        "workflow": {k: data.get(k) for k in WORKFLOW_FACT_KEYS},
        "job_present": isinstance(job, dict),
        "job": {k: job.get(k) for k in JOB_FACT_KEYS} if isinstance(job, dict) else None,
        "step": step,
    }


def workflow_changed(repo: Path, sha: str, parents: list[str]) -> bool:
    """이 커밋이 검증 스텝·게이팅 사실을 바꿨는가. 모르면(해석 불가) 바꾼 것으로 본다."""
    parent = parents[0] if parents else None
    try:
        after = workflow_facts(_blob(repo, sha, WORKFLOW_PATH))
        before = (
            workflow_facts(_blob(repo, parent, WORKFLOW_PATH)) if parent else {"present": False}
        )
    except ValueError:
        return True  # 모른다 ≠ 아니다
    return bool(after != before)


def reasons_for(repo: Path, sha: str, parents: list[str]) -> tuple[str, ...]:
    paths = changed_paths(repo, sha, parents)
    reasons = [f"보호 경로 {p}" for p in paths if is_protected_path(p)]
    if WORKFLOW_PATH in paths and workflow_changed(repo, sha, parents):
        reasons.append(f"{WORKFLOW_PATH} 의 검증 스텝·잡 게이팅 사실")
    return tuple(reasons)


# ─────────────────────────── 서명자·서명 검증 ───────────────────────────
def load_signers(repo: Path, base_commit: str) -> str | None:
    """기준 트리의 서명자 목록 텍스트. 파일이 없으면 None(미무장). 있는데 키가 없으면 측정 불가."""
    text = _blob(repo, base_commit, SIGNERS_PATH)
    if text is None:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if len(line.split()) >= 3 and any(
            tok.startswith(KEY_TYPE_PREFIXES) for tok in line.split()
        ):
            return text
    raise MeasureError(
        f"{SIGNERS_PATH} 가 기준({base_commit[:8]})에 있으나 유효한 서명자 줄이 하나도 없다 — "
        "빈 파일로 검사를 끌 수 없다(미무장은 파일이 *없는* 상태다)"
    )


def signature_of(repo: Path, sha: str, signers_file: Path) -> tuple[str, str, str]:
    """(%G? 코드, 키 지문, 서명자 이름). 전역 gpg 설정(샌드박스 서명 도구 등)은 -c 로 덮는다."""
    raw = git(
        repo,
        "log",
        "-1",
        "--format=%G?%x1f%GK%x1f%GS",
        sha,
        config=(
            "gpg.format=ssh",
            "gpg.ssh.program=ssh-keygen",
            f"gpg.ssh.allowedSignersFile={signers_file}",
        ),
    )
    fields = decode(raw, f"{sha[:8]} 서명 정보").rstrip("\n").split("\x1f")
    fields += [""] * (3 - len(fields))
    return fields[0], fields[1], fields[2]


# ─────────────────────────── 검사 ───────────────────────────
def check(repo: Path, base: str, head: str, event: str) -> tuple[int, str]:
    if event not in VERIFY_EVENTS:
        return 0, (
            f"ℹ️ 이벤트 {event!r} 는 판정하지 않는다 — 이 변경은 PR 시점에 이미 검증됐어야 "
            "큐에 들어올 수 있다(머지 큐 스쿼시는 GitHub 서명이라 Kiki 키가 아니다)"
        )
    if shutil.which("ssh-keygen") is None:
        raise MeasureError("ssh-keygen 을 찾지 못함 — SSH 서명 검증을 할 수 없다")
    base_commit, head_commit = rev(repo, base), rev(repo, head)
    signers = load_signers(repo, base_commit)
    if signers is None:
        return 0, (
            f"⚠️ 미무장 — 기준({base_commit[:8]})에 {SIGNERS_PATH} 가 없다. 서명 요건이 아직 "
            "강제되지 않는다(부트스트랩). Kiki 의 서명 키를 등록하면 무장된다 — "
            "게이트 G-const-signing-key-register · 런북 docs/ops/constitution_signing_runbook.md"
        )
    shas = decode(
        git(repo, "rev-list", "--topo-order", "--reverse", f"{base_commit}..{head_commit}"),
        "rev-list",
    ).split()
    verdicts: list[Verdict] = []
    with tempfile.TemporaryDirectory(prefix="const_signers_") as tmp:
        signers_file = Path(tmp) / "allowed_signers"
        signers_file.write_text(signers, encoding="utf-8")
        for sha in shas:
            parents = decode(git(repo, "rev-list", "--parents", "-n", "1", sha), sha).split()[1:]
            reasons = reasons_for(repo, sha, parents)
            if not reasons:
                continue
            status, fingerprint, principal = signature_of(repo, sha, signers_file)
            subject = decode(git(repo, "log", "-1", "--format=%s", sha), sha).strip()
            verdicts.append(Verdict(sha, subject, reasons, status, fingerprint, principal))
    scope = f"기준 {base_commit[:8]} → {head_commit[:8]} · 커밋 {len(shas)}건"
    if not verdicts:
        return 0, f"✅ 보호 경로를 바꾼 커밋 없음({scope})"
    bad = [v for v in verdicts if not v.ok]
    if not bad:
        who = ", ".join(sorted({v.principal or v.fingerprint for v in verdicts}))
        return (
            0,
            f"✅ 보호 경로 변경 커밋 {len(verdicts)}건이 모두 허용된 키로 서명됨: {who} ({scope})",
        )
    lines = [f"⛔ 허용된 키로 서명되지 않은 보호 경로 변경 {len(bad)}건 ({scope})"]
    for v in bad:
        shown = f"{v.status}" + (f" · 키 {v.fingerprint}" if v.fingerprint else "")
        lines.append(f"   · {v.sha[:8]} {v.subject[:60]} — 서명 상태 {shown}")
        lines.append(f"       서명이 필요한 이유: {'; '.join(v.reasons[:3])}")
    lines.append(
        "   상태 코드: N 서명 없음 · U 유효하나 목록에 없는 키 · B 손상 · G 만 통과. "
        "헌법 변경은 Kiki 의 서명 키로 서명한 커밋으로만 올린다."
    )
    lines.append("   절차: docs/ops/constitution_signing_runbook.md (웹 UI 편집은 서명되지 않는다)")
    return 1, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="헌법 밖 경로 보호 — 서명 검증 (CONST-17)")
    ap.add_argument("--base", default=os.environ.get("CONSTITUTION_BASE_REF") or "origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    args = ap.parse_args(argv)
    try:
        code, message = check(Path(args.repo), args.base, args.head, args.event)
    except MeasureError as exc:
        print(f"⛔ 측정 불가 — {exc}", file=sys.stderr)
        return 2
    if message.startswith("⚠️") and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning title=헌법 서명 검증 미무장::{message}")
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
