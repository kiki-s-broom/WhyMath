#!/usr/bin/env python3
"""scripts/constitution/check_amendment.py — 규칙 R0-02 (코딩 헌법 제11조 ②).

규칙: "constitution/ 이 바뀐 커밋에는 amendments/ 의 새 개정 기록이 함께 있어야 한다."

무엇을 검사하나
  기준(--base)과 머리(--head)의 공통 조상에서 머리까지의 변경을 본다.
  ① `constitution/` 아래 *개정 대상*이 바뀌었는가 — CONSTITUTION.md·rules.yaml·STAGE, 기존 개정
     기록·기존 판례의 수정·삭제·이름 바꿈, 그 밖의 모든 파일. 새 개정 기록(`amendments/`)과 새 판례
     (`precedents/`) **추가**는 개정 대상이 아니다(회고 추가는 제11조 ④의 일이다).
  ② 개정 대상이 바뀌었다면 같은 변경에 새 개정 기록(`amendments/A####_*.md` 추가)이 있는가.
  ③ 새 개정 기록이 빈 껍데기가 아닌가 — 이름 패턴·제목의 번호 일치·날짜·최소 분량·번호 유일성.

일부러 요구하지 않는 것(정상 개정을 막지 않기 위해 — 제11조는 사람이 헌법을 고칠 수 있어야 한다)
  · 번호가 이전보다 커야 한다는 단조 증가 — A0003 이 A0002 보다 먼저 채택됐다.
  · 특정 제목(`## 사유`·`## 영향 범위`) — 기존 기록 3건의 제목이 서로 다르다.
  ※ 기록의 *내용이 변경을 정확히 설명하는지*는 기계가 판정하지 못한다(사람의 몫).

종료 코드: 0 통과(헌법 변경 없음 · 개정 기록만 추가 · 새 기록 동반) / 1 위반 / 2 측정 불가
  측정 불가(기준을 못 찾음·공통 조상 없음·git 실패)를 통과로 돌리지 않는다 — '0건 통과' 위장 금지.

사용: python scripts/constitution/check_amendment.py [--base REF] [--head REF] [--repo DIR]
  --base 기본값: 환경변수 CONSTITUTION_BASE_REF, 없으면 origin/main
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# 윈도우 콘솔(cp949)에서 한글이 깨져 스크립트가 죽지 않도록 UTF-8로 출력
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[2]
CONSTITUTION_DIR = "constitution/"
AMENDMENTS_DIR = "constitution/amendments/"
PRECEDENTS_DIR = "constitution/precedents/"
RECORD_NAME = re.compile(r"A(\d{4})_[^/]+\.md")
ISO_DATE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
MIN_RECORD_CHARS = 200  # 사유·영향·날짜를 적은 기록이 이보다 짧을 수 없다 — 빈 껍데기 차단
GIT_TIMEOUT_SEC = 60


class MeasureError(Exception):
    """측정 불가 — 호출자가 종료 코드 2 로 바꾼다(통과로 위장하지 않는다)."""


@dataclass(frozen=True)
class Change:
    status: str  # A·M·D·T 등 git name-status 첫 글자
    path: str


def git(repo: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            timeout=GIT_TIMEOUT_SEC,
            check=False,
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
    return decode(git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"), ref).strip()


def changes_since_fork(repo: Path, base: str, head: str) -> tuple[str, list[Change]]:
    """base 와 head 의 공통 조상 → head 의 변경 목록. 이름 바꿈은 삭제+추가로 본다(--no-renames)."""
    try:
        base_commit, head_commit = rev(repo, base), rev(repo, head)
    except MeasureError as exc:
        raise MeasureError(
            f"기준·머리 ref 를 찾지 못함(base={base}, head={head}) — CI 라면 checkout 의 "
            f"fetch-depth: 0 이 필요하다: {exc}"
        ) from exc
    try:
        fork = decode(git(repo, "merge-base", base_commit, head_commit), "merge-base").strip()
    except MeasureError as exc:
        raise MeasureError(
            f"공통 조상이 없음 — shallow 클론이거나 무관한 히스토리다: {exc}"
        ) from exc
    raw = git(repo, "diff", "-z", "--name-status", "--no-renames", fork, head_commit)
    parts = decode(raw, "git diff 출력").split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 2 != 0:
        raise MeasureError(f"git diff -z 출력 해석 실패(토큰 {len(parts)}개 — 짝수여야 한다)")
    found = [Change(parts[i][0], parts[i + 1]) for i in range(0, len(parts), 2)]
    return fork, found


def is_amendment_target(change: Change) -> bool:
    """개정 대상(= 개정 기록이 필요한 변경)인가."""
    if not change.path.startswith(CONSTITUTION_DIR):
        return False
    if change.status == "A" and change.path.startswith(AMENDMENTS_DIR):
        return False  # 새 개정 기록 추가 자체는 개정이 아니다
    if change.status == "A" and change.path.startswith(PRECEDENTS_DIR):
        return False  # 새 판례(회고) 추가는 제11조 ④ — 개정이 아니다
    return True


def new_record_problems(repo: Path, fork: str, head: str, added: list[Change]) -> list[str]:
    """새 개정 기록 각각의 빈 껍데기 여부·번호 유일성."""
    existing = decode(git(repo, "ls-tree", "--name-only", fork, AMENDMENTS_DIR), "ls-tree")
    taken = {
        m.group(1)
        for line in existing.splitlines()
        if (m := RECORD_NAME.fullmatch(Path(line).name))
    }
    problems: list[str] = []
    seen_in_diff: dict[str, str] = {}
    for change in added:
        name = change.path[len(AMENDMENTS_DIR) :]
        match = RECORD_NAME.fullmatch(name)
        assert match is not None  # 호출자(check)가 이름이 맞는 기록만 넘긴다
        number = match.group(1)
        if number in taken:
            problems.append(f"{change.path}: 번호 A{number} 가 이미 있다(기존 기록과 번호 충돌)")
        if number in seen_in_diff:
            problems.append(f"{change.path}: 번호 A{number} 가 {seen_in_diff[number]} 와 겹친다")
        seen_in_diff[number] = change.path
        text = decode(git(repo, "show", f"{head}:{change.path}"), change.path)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines or not lines[0].lstrip().startswith("#"):
            problems.append(f"{change.path}: 첫 줄이 제목(#)이 아님")
        elif f"A{number}" not in lines[0]:
            problems.append(
                f"{change.path}: 제목에 번호 A{number} 가 없음 — 파일명과 제목이 어긋남"
            )
        if len(text.strip()) < MIN_RECORD_CHARS:
            problems.append(
                f"{change.path}: 분량 {len(text.strip())}자 < {MIN_RECORD_CHARS}자 — 빈 껍데기 의심"
            )
        if ISO_DATE.search(text) is None:
            problems.append(f"{change.path}: 날짜(YYYY-MM-DD)가 없음 — 제11조 ②는 날짜를 요구한다")
    return problems


def check(repo: Path, base: str, head: str) -> tuple[int, str]:
    fork, found = changes_since_fork(repo, base, head)
    targets = [c for c in found if is_amendment_target(c)]
    added = [c for c in found if c.status == "A" and c.path.startswith(AMENDMENTS_DIR)]
    # 이름이 A####_*.md 인 것만 '개정 기록'이다. README.md·.gitkeep 같은 *다른 파일*은 기록이
    # 아니므로 무시한다 — 정상 기록과 같이 들어왔다고 PR 전체를 막으면 오류 문구("기록으로 세지
    # 않는다")와 동작이 어긋난다. 기록이 하나도 없으면 아래에서 무시한 파일을 병기해 막는다.
    records = [c for c in added if RECORD_NAME.fullmatch(c.path[len(AMENDMENTS_DIR) :])]
    strays = [c for c in added if c not in records]
    scope = f"공통 조상 {fork[:8]} → {head} · 변경 {len(found)}건"
    if not targets:
        extra = f" · 새 개정 기록 {len(records)}건" if records else ""
        return 0, f"✅ 개정 대상 변경 없음({scope}{extra})"
    listing = ", ".join(f"{c.status}:{c.path}" for c in targets[:5]) + (
        f" 외 {len(targets) - 5}건" if len(targets) > 5 else ""
    )
    if not records:
        ignored = ""
        if strays:
            names = ", ".join(c.path[len(AMENDMENTS_DIR) :] for c in strays)
            ignored = f"\n   (이름이 A####_*.md 형식이 아니라 기록으로 세지 않은 파일: {names})"
        return 1, (
            f"⛔ 헌법이 바뀌었는데 새 개정 기록이 없다({scope}). 개정 대상: {listing}\n"
            f"   제11조 ②: {AMENDMENTS_DIR} 에 A####_*.md 로 "
            "개정 번호·사유·영향 범위·날짜를 남긴다.\n"
            "   (헌법 개정은 사람만 한다 — AI 세션이 이 상태를 만들었다면 가드 훅을 우회한 것이다.)"
            f"{ignored}"
        )
    problems = new_record_problems(repo, fork, head, records)
    if problems:
        return 1, "⛔ 새 개정 기록이 요건을 못 채운다:\n" + "\n".join(f"   · {p}" for p in problems)
    names = ", ".join(c.path[len(AMENDMENTS_DIR) :] for c in records)
    return 0, f"✅ 헌법 변경({len(targets)}건)에 새 개정 기록이 동반됨: {names} ({scope})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="헌법 개정 기록 동반 검사 (R0-02 · 제11조 ②)")
    ap.add_argument("--base", default=os.environ.get("CONSTITUTION_BASE_REF") or "origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--repo", default=str(ROOT))
    args = ap.parse_args(argv)
    try:
        code, message = check(Path(args.repo), args.base, args.head)
    except MeasureError as exc:
        print(f"⛔ 측정 불가 — {exc}", file=sys.stderr)
        return 2
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
