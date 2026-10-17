#!/usr/bin/env python3
"""Feature Freeze / Code Freeze 날짜 기반 PR 검사 (HARN-103).

왜 이 도구가 있는가
-------------------
EOS 계획서는 11/30 Feature Freeze · 12/14 Code Freeze를 "코드/프로세스로 **실제** 적용"하라고
요구한다. 규칙 문서만 있으면 동결은 의지 표명일 뿐이다(정본화≠집행). 이 스크립트가 문서의
날짜·라벨·경로 규칙을 PR 단위로 판정하는 **집행 지점**이다. 규칙의 사람말 정본은
`docs/standards/release_freeze.md`이고, 둘의 날짜·라벨 일치는
`tests/infra/test_release_freeze.py`가 동결한다.

판정 규칙 (정본은 문서 — 여기는 구현)
-----------------------------------
    단계            날짜                       동결 경로 변경 시 필요한 라벨
    OPEN            ~ 2026-11-29               없음 (검사 통과)
    FEATURE_FREEZE  2026-11-30 ~ 12-13         release-blocker
    CODE_FREEZE     2026-12-14 ~ 2027-01-14    release-blocker + code-freeze-approved
    RELEASED        2027-01-15 ~               없음 (동결 자동 해제)

* 동결 경로가 아닌 파일(문서·테스트·백로그 대장 등)만 바꾸는 PR은 어느 단계에서도 통과한다.
* **동결에는 만료가 있다** — RELEASED 단계는 사람의 해제 조작 없이 날짜로 온다. 만료 없는
  동결은 이 저장소가 금지한 유예 그 자체라(CLAUDE.md '만료 없는 유예·제외 금지') 해제를
  기억에 맡기지 않는다. 연장하려면 문서와 이 상수를 함께 고쳐야 하고 테스트가 둘의 일치를 강제한다.

exit code (셋 다 서로 구별된다 — "측정 실패"가 "통과"로 위장되면 안 된다)
    0 = 통과 (OPEN·RELEASED이거나, 동결 경로 변경이 없거나, 필요한 라벨이 다 있음)
    1 = 위반 (동결 단계에서 동결 경로를 바꾸는데 라벨이 모자람)
    2 = 측정 실패 (변경 파일을 못 구함·날짜 형식 오류·일정 상수가 모순)

한계 (정직하게)
---------------
* `code-freeze-approved` 라벨을 **누가 붙였는지**는 이 스크립트가 모른다. 라벨 부착은
  triage 권한이면 누구나 가능하므로, 이 라벨은 승인의 증거가 아니라 **승인 요청이 가시화됐다는
  표지**다. 승인 주체를 강제하려면 CODEOWNERS·룰셋 승인 규칙(Kiki 소유 설정)이 필요하다.
* 의미(기능 추가냐 버그 수정이냐)는 판정하지 못한다. 경로와 라벨만 본다.

사용
----
    python3 scripts/ops/check_release_freeze.py --labels release-blocker --base origin/main
    python3 scripts/ops/check_release_freeze.py --files-from changed.txt --today 2026-12-20
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 일정. 문서(`docs/standards/release_freeze.md`)의 표와 테스트가 일치를 강제한다.
FEATURE_FREEZE_START = date(2026, 11, 30)
CODE_FREEZE_START = date(2026, 12, 14)
#: 동결 해제 지점. 12/31 검증 판정(Go/Conditional Go/No-Go) 뒤 정리 기간을 둔 날짜다.
FREEZE_EXPIRES = date(2027, 1, 15)

LABEL_RELEASE_BLOCKER = "release-blocker"
LABEL_CODE_FREEZE_APPROVED = "code-freeze-approved"

#: 동결 경로 — 제품 동작을 바꾸는 트리. 문서·테스트·백로그 대장은 제외(변경해도 제품이 안 바뀐다).
FROZEN_PREFIXES: tuple[str, ...] = ("src/", "infra/", "schemas/")
#: Code Freeze부터 추가되는 경로 — 콘텐츠 데이터(12/27 데이터 동결 전 마지막 보호막).
CODE_FREEZE_EXTRA_PREFIXES: tuple[str, ...] = ("data/",)

PHASE_OPEN = "OPEN"
PHASE_FEATURE_FREEZE = "FEATURE_FREEZE"
PHASE_CODE_FREEZE = "CODE_FREEZE"
PHASE_RELEASED = "RELEASED"


class MeasurementError(Exception):
    """판정 자체를 못 한 경우 — 통과가 아니라 exit 2."""


@dataclass(frozen=True)
class Verdict:
    phase: str
    frozen_files: tuple[str, ...]
    required_labels: tuple[str, ...]
    missing_labels: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (self.frozen_files and self.missing_labels)


def validate_schedule() -> None:
    """일정 상수가 모순이면 판정하지 않는다(모순된 일정으로 낸 통과는 위장이다)."""
    if not FEATURE_FREEZE_START < CODE_FREEZE_START < FREEZE_EXPIRES:
        raise MeasurementError(
            "일정 상수가 단조 증가가 아니다: "
            f"{FEATURE_FREEZE_START} < {CODE_FREEZE_START} < {FREEZE_EXPIRES}"
        )


def phase_of(today: date) -> str:
    validate_schedule()
    if today < FEATURE_FREEZE_START:
        return PHASE_OPEN
    if today < CODE_FREEZE_START:
        return PHASE_FEATURE_FREEZE
    if today < FREEZE_EXPIRES:
        return PHASE_CODE_FREEZE
    return PHASE_RELEASED


def frozen_prefixes(phase: str) -> tuple[str, ...]:
    if phase == PHASE_FEATURE_FREEZE:
        return FROZEN_PREFIXES
    if phase == PHASE_CODE_FREEZE:
        return FROZEN_PREFIXES + CODE_FREEZE_EXTRA_PREFIXES
    return ()


def required_labels(phase: str) -> tuple[str, ...]:
    if phase == PHASE_FEATURE_FREEZE:
        return (LABEL_RELEASE_BLOCKER,)
    if phase == PHASE_CODE_FREEZE:
        return (LABEL_RELEASE_BLOCKER, LABEL_CODE_FREEZE_APPROVED)
    return ()


def evaluate(today: date, labels: set[str], changed_files: list[str]) -> Verdict:
    phase = phase_of(today)
    prefixes = frozen_prefixes(phase)
    frozen = tuple(f for f in changed_files if f.startswith(prefixes)) if prefixes else ()
    need = required_labels(phase)
    missing = tuple(label for label in need if label not in labels)
    return Verdict(phase, frozen, need, missing)


def changed_files_from_git(base: str) -> list[str]:
    """`base...HEAD` 변경 파일. 조회 실패는 빈 목록이 아니라 측정 실패다."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MeasurementError(f"git diff 실행 실패: {type(exc).__name__}") from exc
    if proc.returncode != 0:
        raise MeasurementError(
            f"git diff {base}...HEAD 실패(exit {proc.returncode}): {proc.stderr.strip()[:200]}"
        )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def parse_today(raw: str | None) -> date:
    if raw is None:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise MeasurementError(f"--today 형식 오류(YYYY-MM-DD 필요): {raw!r}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", default="", help="PR 라벨(쉼표 구분)")
    parser.add_argument("--base", default="origin/main", help="변경 파일 기준 ref")
    parser.add_argument("--files-from", help="변경 파일 목록 파일(줄 단위). 주면 git을 쓰지 않는다")
    parser.add_argument("--today", help="판정 기준일 YYYY-MM-DD (기본: UTC 오늘)")
    parser.add_argument("--json", action="store_true", help="기계 판독용 출력")
    args = parser.parse_args(argv)

    try:
        today = parse_today(args.today)
        if args.files_from:
            try:
                text = Path(args.files_from).read_text(encoding="utf-8")
            except OSError as exc:
                raise MeasurementError(f"--files-from 읽기 실패: {type(exc).__name__}") from exc
            files = [line for line in text.splitlines() if line.strip()]
        else:
            files = changed_files_from_git(args.base)
        labels = {x.strip() for x in args.labels.split(",") if x.strip()}
        verdict = evaluate(today, labels, files)
    except MeasurementError as exc:
        print(f"[freeze] 측정 실패 — 통과가 아니다: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = {"today": today.isoformat(), **asdict(verdict), "ok": verdict.ok}
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(
            f"[freeze] 단계={verdict.phase} 기준일={today} "
            f"변경 {len(files)}건 중 동결 경로 {len(verdict.frozen_files)}건"
        )
    if verdict.ok:
        return 0
    need = ", ".join(verdict.required_labels)
    lack = ", ".join(verdict.missing_labels)
    print(
        f"[freeze] 위반 — {verdict.phase} 단계에서 동결 경로를 바꾸려면 라벨 {need} 이(가) "
        f"필요한데 {lack} 이(가) 없다.",
        file=sys.stderr,
    )
    for path in verdict.frozen_files[:20]:
        print(f"  · {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
