#!/usr/bin/env python3
"""낡은 데모 DB 판정 — 데모 DB가 기억하는 alembic 리비전이 현재 코드에 있는가 (OPS-133).

**왜 이것이 필요한가**: `run_demo.ps1`은 예전에 돌린 `whymath-demo-db` 컨테이너를 그대로 재기동한다.
그 DB의 `alembic_version`이 *main에 없는* 리비전(닫힌 PR·미머지 브랜치에서 마이그레이션을 돌린
흔적)을 가리키면 `alembic upgrade head`는 "Can't locate revision identified by '...'"로 죽는다.
2026-10-12 G-ops106-gate2-live-sample 실행에서 실측됐다(리비전 `79de95331710` = 닫힌 PR #880).

**판정을 alembic 출력 문자열 파싱이 아니라 DB 리비전 대조로 하는 이유**: 오류 문구는 alembic 버전에
따라 바뀌고, 한국어 Windows에서 네이티브 출력을 PowerShell로 중계하면 인코딩이 깨질 수 있다. 원인 그
자체(= DB가 기억하는 리비전이 코드에 없다)를 직접 대조하면 문구에 의존하지 않는다.

**3상태 판정** (모른다 ≠ 아니다):
  - 종료 0 `CLEAN`   : DB 리비전이 전부 코드에 있다 — 낡은 DB가 원인이 아니다.
  - 종료 1 `STALE`   : 코드에 없는 리비전이 하나 이상 있다 — 낡은 데모 DB.
  - 종료 2 `UNKNOWN` : 판정할 수 없다(DB 리비전 0건·코드 리비전 0건·형식이 이상한 토큰).
    이 경우 낡은 DB라고도, 아니라고도 단정하지 않는다.

표준 라이브러리만 쓴다(데모 호스트의 venv 상태·CI 파이썬 버전과 무관하게 동작).
출력은 ASCII 전용이다(cp949 로케일에서 PowerShell로 중계돼도 깨지지 않게).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 리포 루트 = scripts/demo/diagnose_stale_demo_db.py에서 2단계 상위.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VERSIONS_DIR = _REPO_ROOT / "src" / "backend" / "alembic" / "versions"

# 리비전 파일 머리말: `revision: str = "abc"` 또는 `revision = "abc"`(down_revision은 `^`로 배제).
_REVISION_LINE = re.compile(r"""^revision(?:\s*:\s*[^=]+)?\s*=\s*["']([0-9A-Za-z_]+)["']""", re.M)
# alembic 리비전 ID로 쓸 수 있는 토큰 — psql 오류 문구 같은 쓰레기를 "낡은 DB"로 오판하지 않는다.
_REVISION_TOKEN = re.compile(r"^[0-9A-Za-z_]{4,64}$")


class Verdict:
    CLEAN = "CLEAN"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


EXIT_CODES = {Verdict.CLEAN: 0, Verdict.STALE: 1, Verdict.UNKNOWN: 2}


def known_revisions(versions_dir: Path) -> set[str]:
    """`versions/*.py`가 선언한 리비전 ID 전부. 디렉터리가 없거나 비면 빈 집합."""
    found: set[str] = set()
    if not versions_dir.is_dir():
        return found
    for path in sorted(versions_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        match = _REVISION_LINE.search(path.read_text(encoding="utf-8", errors="replace"))
        if match:
            found.add(match.group(1))
    return found


def judge(db_revisions: list[str], known: set[str]) -> tuple[str, list[str]]:
    """(판정, 코드에 없는 리비전 목록). 판정 불가 조건은 전부 UNKNOWN으로 접는다."""
    if not known:
        # 스캔 0건은 실패 — 코드 쪽 리비전을 하나도 못 읽었는데 "전부 낡았다"고 말하면 위장이다.
        return Verdict.UNKNOWN, []
    cleaned = [r.strip() for r in db_revisions if r.strip()]
    if not cleaned or any(not _REVISION_TOKEN.match(r) for r in cleaned):
        return Verdict.UNKNOWN, []
    unknown = sorted({r for r in cleaned if r not in known})
    return (Verdict.STALE, unknown) if unknown else (Verdict.CLEAN, [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db-revisions",
        nargs="*",
        default=[],
        help="데모 DB의 alembic_version.version_num 값들(0개면 UNKNOWN)",
    )
    parser.add_argument("--versions-dir", type=Path, default=DEFAULT_VERSIONS_DIR)
    args = parser.parse_args(argv)

    known = known_revisions(args.versions_dir)
    verdict, unknown = judge(list(args.db_revisions), known)
    print(
        f"DEMO_DB_VERDICT={verdict} UNKNOWN_REVISIONS={','.join(unknown)} "
        f"KNOWN_COUNT={len(known)} DB_COUNT={len(args.db_revisions)}"
    )
    return EXIT_CODES[verdict]


if __name__ == "__main__":
    sys.exit(main())
