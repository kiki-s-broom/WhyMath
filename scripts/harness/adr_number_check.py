#!/usr/bin/env python3
"""ADR 번호 충돌 검사 — 원격 전 브랜치 + 체크아웃 HEAD를 스캔한다 (HARN-66).

`backlog.py add`가 태스크 번호에 하는 일을 ADR 번호에 한다.

## 왜 원격까지 보는가

작업 트리의 `ls docs/architecture/adr/`는 **"trunk에 무엇이 있는가"만** 말한다. 장기 미머지
브랜치가 수십 개인 이 저장소에서 그것은 "다음 빈 번호"를 알려주지 못한다.

사고 경위(2026-09-05): ADR 번호 계열 규약을 만든 세션이 `ls`로 "다음 빈 번호 = 003"을 골라
`ADR-003-subject-contract-v1-provisional.md`를 만들었다. 그러나
`origin/claude/entity-model-freeze-lji37v`가 같은 날 **15:45**에
`ADR-003-subject-prefix-is-convention-not-entity.md`를 선점했고, 그 세션의 커밋은 **16:58**로
나중이었다 — **번호 충돌을 막으려던 문서가 충돌을 하나 더 만들었다**(ADR-004로 개명 상환).

같은 세션에서 *태스크* 번호는 `backlog.py add`가 원격 claim까지 검사해 `EOS-83` 충돌을
**거부**했다. 규칙이 아니라 **집행 장치의 유무**가 갈랐다 — 이 파일이 그 장치다.

## 무엇을 스캔하는가

원격(`origin`)이 광고하는 **모든 브랜치** + 지금 체크아웃된 **HEAD**. HEAD를 넣는 이유: fork
PR의 merge ref나 아직 push하지 않은 로컬 작업은 원격 브랜치가 아니므로, 원격만 보면 *제안된
바로 그 변경*이 검사에서 빠진다(PR #1011 리뷰 P2).

## 판정

번호 하나가 **서로 다른 슬러그 2개 이상**에 쓰이면 충돌이다. 번호는 정수로 정규화한다 —
`ADR-1-x.md`와 `ADR-001-y.md`는 같은 번호 1이다(PR #1011 리뷰 P2). 같은 번호·같은 파일명이 여러
브랜치에 있는 것은 정상(같은 문서가 퍼진 것뿐).

exit 0 = 충돌 없음 · exit 1 = 충돌 또는 **측정 실패**.

측정 실패를 통과로 만들지 않는다. 세 경우 전부 exit 1이다:
  · 원격 조회가 안 됨 — 검사 자체가 성립하지 않는다
  · 광고된 브랜치 중 **하나라도** 로컬에서 읽을 수 없음 — 부분 스캔은 스캔이 아니다. 그 한
    브랜치에 충돌이 있을 수 있고, 그것을 건너뛰고 낸 초록은 "위반 없음"과 화면이 같다
    (PR #1011 리뷰 P1 — 초판은 이 경우를 조용히 비웠고, "정직한 공백"에 적어 놓고 그대로
    배포했다. 알면서 남긴 결함이었다)
  · ADR을 하나도 못 찾음 — 대상 0건의 전수 가드는 공허하게 통과한다
(CLAUDE.md "상시 실패하는 fail-open 보호를 '보호 있음'으로 신뢰 금지" · "스캔 0건은 실패")
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict

ADR_DIR = "docs/architecture/adr"

# ADR-003-subject-prefix-....md → (숫자 문자열 "003", 슬러그). 자릿수는 여기서 제한하지 않고
# 아래에서 정수로 정규화한다 — "ADR-1-"도 잡아서 같은 번호로 접어야 충돌이 보인다.
_ADR_FILENAME_RE = re.compile(r"^ADR-(\d+)-(.+)\.md$")

# 외부 프로세스에는 전부 타임아웃을 건다 (CLAUDE.md 2026-08-22 — 무한 대기로 측정 회차를
# 태우지 않는다). 원격 조회는 프록시를 타므로 로컬 명령보다 넉넉히 준다.
_LS_REMOTE_TIMEOUT = 60
_LS_TREE_TIMEOUT = 30

# 체크아웃된 리비전의 라벨. 충돌 보고에 브랜치 이름 대신 이 라벨이 뜨면 "지금 제안된 변경"이
# 한쪽 당사자라는 뜻이다.
HEAD_LABEL = "HEAD(체크아웃)"


class ScanError(RuntimeError):
    """스캔이 성립하지 않았다 — 통과가 아니라 실패로 보고할 상태."""


def _git(args: list[str], timeout: int) -> str:
    """git 명령을 돌리고 stdout을 돌려준다.

    인코딩을 **명시**한다 — Windows 로케일(cp949)에서 기본 인코딩 디코드는 붕괴한다
    (CLAUDE.md·HARN-19 실측). 실패는 삼키지 않고 stderr를 담아 올린다(침묵 실패 금지).
    """
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", *args],
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise ScanError(f"git {' '.join(args)} — {timeout}초 타임아웃") from exc
    except OSError as exc:
        raise ScanError(f"git {' '.join(args)} — {type(exc).__name__}: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or "(stderr 없음)"
        raise ScanError(f"git {' '.join(args)} — exit {proc.returncode}: {detail}")
    return proc.stdout


def remote_branches(remote: str) -> list[str]:
    """원격이 광고하는 브랜치 이름 전건."""
    out = _git(["ls-remote", "--heads", remote], _LS_REMOTE_TIMEOUT)
    names = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            names.append(parts[1][len("refs/heads/") :])
    if not names:
        raise ScanError(f"원격 '{remote}'에서 브랜치를 하나도 찾지 못했다 — 스캔이 성립하지 않는다")
    return names


def adr_files_on(ref: str) -> list[str]:
    """한 ref의 ADR 디렉터리 파일명 목록.

    ref는 읽히는데 그 디렉터리가 없으면 빈 목록(정상). ref 자체를 읽지 못하면 **ScanError**다 —
    조용히 빈 목록으로 접지 않는다. `git ls-tree`는 두 경우를 exit code로 구분해 준다
    (없는 경로 = exit 0·빈 출력 / 없는 ref = exit 128).
    """
    out = _git(["ls-tree", "-r", "--name-only", ref, "--", ADR_DIR + "/"], _LS_TREE_TIMEOUT)
    return [line.rsplit("/", 1)[-1] for line in out.splitlines() if line.strip()]


def collect(targets: list[tuple[str, str]]) -> dict[str, dict[str, set[str]]]:
    """번호(3자리 정규화) → {슬러그 → 그 슬러그를 담은 대상 라벨 집합}.

    `targets`는 (라벨, ref) 쌍이다. 읽지 못한 대상은 **모아서 한 번에** 올린다 — 하나씩
    올리면 사람이 고칠 때마다 다음 것을 새로 만나게 되고, 그것이 가드를 끄게 만든다.
    """
    seen: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    unreadable: list[str] = []
    found_any = False
    for label, ref in targets:
        try:
            names = adr_files_on(ref)
        except ScanError as exc:
            unreadable.append(f"{label} ({ref}): {exc}")
            continue
        for name in names:
            m = _ADR_FILENAME_RE.match(name)
            if m:
                found_any = True
                number = f"{int(m.group(1)):03d}"  # "1"·"01"·"001" → "001"
                seen[number][m.group(2)].add(label)
    if unreadable:
        raise ScanError(
            f"광고된 대상 {len(unreadable)}건을 읽지 못했다 — 부분 스캔은 스캔이 아니다.\n"
            "  " + "\n  ".join(unreadable) + "\n"
            "  CI라면 전 브랜치 fetch 스텝이 이 스크립트보다 앞에 있는지 확인하라.\n"
            "  로컬이라면: git fetch origin '+refs/heads/*:refs/remotes/origin/*'"
        )
    if not found_any:
        raise ScanError(
            f"어느 대상에서도 ADR 파일을 찾지 못했다 ({len(targets)}건 스캔) — "
            f"{ADR_DIR}/ 가 비어 있거나 없다. 대상 0건은 통과가 아니다."
        )
    return seen


def scan_targets(remote: str, branches: list[str]) -> list[tuple[str, str]]:
    """스캔 대상 = 원격 브랜치 전건 + 체크아웃 HEAD."""
    targets = [(b, f"refs/remotes/{remote}/{b}") for b in branches]
    targets.append((HEAD_LABEL, "HEAD"))
    return targets


def next_free(numbers: set[str]) -> str:
    """사용 중이지 않은 가장 작은 번호를 3자리로."""
    used = {int(n) for n in numbers}
    candidate = 1
    while candidate in used:
        candidate += 1
    return f"{candidate:03d}"


def main() -> int:
    parser = argparse.ArgumentParser(description="ADR 번호 충돌 검사 (원격 전 브랜치 + HEAD 스캔)")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()

    try:
        branches = remote_branches(args.remote)
        seen = collect(scan_targets(args.remote, branches))
    except ScanError as exc:
        # 측정 실패는 통과가 아니다 — "0건 통과"로 위장되면 안 된다.
        print(f"❌ ADR 번호 스캔 실패 — 이 검사는 성립하지 않았다\n   {exc}", file=sys.stderr)
        return 1

    conflicts = {num: slugs for num, slugs in seen.items() if len(slugs) > 1}
    total = sum(len(slugs) for slugs in seen.values())

    if conflicts:
        print(f"❌ ADR 번호 충돌 {len(conflicts)}건 — 같은 번호가 서로 다른 문서를 가리킨다")
        for num in sorted(conflicts):
            print(f"\n  ADR-{num}:")
            for slug, where in sorted(conflicts[num].items()):
                print(f"    · ADR-{num}-{slug}.md  ({', '.join(sorted(where))})")
        print(
            f"\n다음 빈 번호 제안: ADR-{next_free(set(seen))}"
            "\n(규약 정본 = docs/architecture/adr/README.md §번호를 고르는 법)"
        )
        return 1

    print(
        f"✔ ADR 번호 충돌 없음 — 브랜치 {len(branches)}개 + HEAD 스캔, "
        f"문서 {total}건, 번호 {len(seen)}개. 다음 빈 번호: ADR-{next_free(set(seen))}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
