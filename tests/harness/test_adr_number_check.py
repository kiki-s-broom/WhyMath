"""ADR 번호 충돌 검사 계약 동결 (HARN-66).

이 테스트가 지키는 것은 "검사기가 존재한다"가 아니라 **"실패 상태에서 실제로 빨강을 낸다"**이다
(CLAUDE.md 2026-09-01 "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지").

그래서 세 축을 전부 실측한다:
  ① 충돌 주입 → exit 1   ② 정상 → exit 0   ③ 스캔 0건 → exit 1(공허한 통과 금지)

②가 없으면 "항상 빨강"인 가드도 ①을 통과하고, ③이 없으면 대상을 하나도 못 찾은 가드가
조용히 초록을 낸다 — 세 축이 함께 있어야 변별력이 성립한다.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "harness" / "adr_number_check.py"
ADR_DIR = "docs/architecture/adr"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", *args], cwd=cwd, check=True, capture_output=True, encoding="utf-8"
    )


def _write(repo: Path, rel: str, body: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _init_upstream(tmp_path: Path) -> Path:
    """ADR 1건을 담은 main 브랜치짜리 업스트림 저장소."""
    up = tmp_path / "up"
    up.mkdir()
    _git(up, "init", "-q", "-b", "main")
    _git(up, "config", "user.email", "t@example.com")
    _git(up, "config", "user.name", "t")
    _write(up, f"{ADR_DIR}/ADR-001-alpha.md", "# ADR-001\n")
    _git(up, "add", "-A")
    _git(up, "commit", "-qm", "init")
    return up


def _branch_with(up: Path, branch: str, filename: str) -> None:
    _git(up, "checkout", "-q", "main")
    _git(up, "checkout", "-qb", branch)
    _write(up, f"{ADR_DIR}/{filename}", "# x\n")
    _git(up, "add", "-A")
    _git(up, "commit", "-qm", branch)
    _git(up, "checkout", "-q", "main")


def _clone(tmp_path: Path, up: Path) -> Path:
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(up), str(work))
    _git(work, "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")
    return work


def _run(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(CHECKER)], cwd=cwd, capture_output=True, encoding="utf-8"
    )


def test_conflict_across_branches_is_red(tmp_path: Path) -> None:
    """서로 다른 브랜치가 같은 번호를 다른 슬러그로 쓰면 거부한다.

    2026-09-05 실사고의 재현이다 — 한쪽은 `ADR-003-subject-prefix-...`, 다른 쪽은
    `ADR-003-subject-contract-...`였고 **작업 트리 `ls`로는 둘 다 보이지 않았다**.
    """
    up = _init_upstream(tmp_path)
    _branch_with(up, "feat-a", "ADR-003-foo.md")
    _branch_with(up, "feat-b", "ADR-003-bar.md")
    work = _clone(tmp_path, up)

    result = _run(work)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ADR-003" in result.stdout
    # 충돌한 *양쪽*과 각각이 사는 브랜치를 지목해야 사람이 고칠 수 있다.
    assert "ADR-003-foo.md" in result.stdout
    assert "ADR-003-bar.md" in result.stdout
    assert "feat-a" in result.stdout
    assert "feat-b" in result.stdout


def test_next_free_number_is_suggested_on_reject(tmp_path: Path) -> None:
    """거부는 반드시 쓸 수 있는 번호를 함께 준다 (acceptance ④).

    고칠 방법 없는 거부는 사람이 게이트를 끄게 만든다 — `backlog.py add`가 번호 충돌에서
    다음 빈 번호를 제안하는 것과 같은 이유다.
    """
    up = _init_upstream(tmp_path)
    _branch_with(up, "feat-a", "ADR-002-foo.md")
    _branch_with(up, "feat-b", "ADR-002-bar.md")
    work = _clone(tmp_path, up)

    result = _run(work)

    assert result.returncode == 1
    # 001·002가 쓰였으므로 003을 제안해야 한다.
    assert "다음 빈 번호 제안: ADR-003" in result.stdout


def test_same_document_on_many_branches_is_green(tmp_path: Path) -> None:
    """같은 번호·같은 파일명이 여러 브랜치에 퍼진 것은 충돌이 아니다.

    대조군이다. 이것이 빨강이면 검사기는 정상 저장소에서 상시 실패하고, 상시 실패하는
    보호는 보호가 아니라 소음이 된다(CLAUDE.md 금기).
    """
    up = _init_upstream(tmp_path)
    _branch_with(up, "feat-a", "ADR-002-same.md")
    _branch_with(up, "feat-b", "ADR-002-same.md")
    work = _clone(tmp_path, up)

    result = _run(work)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "충돌 없음" in result.stdout


def test_empty_scan_is_red_not_green(tmp_path: Path) -> None:
    """ADR을 하나도 못 찾으면 통과가 아니라 실패다 (acceptance ②).

    전수 가드가 대상 0건에서 초록을 내면 그것은 "위반이 없다"가 아니라 "보지 않았다"이며,
    두 상태는 화면에서 구별되지 않는다.
    """
    up = tmp_path / "up"
    up.mkdir()
    _git(up, "init", "-q", "-b", "main")
    _git(up, "config", "user.email", "t@example.com")
    _git(up, "config", "user.name", "t")
    _write(up, "readme.md", "x\n")
    _git(up, "add", "-A")
    _git(up, "commit", "-qm", "init")
    work = _clone(tmp_path, up)

    result = _run(work)

    assert result.returncode == 1
    assert "스캔 실패" in result.stderr


def test_missing_remote_is_red(tmp_path: Path) -> None:
    """원격이 없으면 측정 실패로 거부한다 — "0건 통과"로 위장되지 않는다."""
    solo = tmp_path / "solo"
    solo.mkdir()
    _git(solo, "init", "-q", "-b", "main")
    _git(solo, "config", "user.email", "t@example.com")
    _git(solo, "config", "user.name", "t")
    _write(solo, f"{ADR_DIR}/ADR-001-alpha.md", "# a\n")
    _git(solo, "add", "-A")
    _git(solo, "commit", "-qm", "init")

    result = _run(solo)

    assert result.returncode == 1
    assert "스캔 실패" in result.stderr


@pytest.mark.parametrize(
    ("used", "expected"),
    [
        ({"001", "002"}, "003"),
        ({"001", "003"}, "002"),  # 중간 구멍을 메운다
        (set(), "001"),
        ({"001", "002", "003", "004"}, "005"),
    ],
)
def test_next_free_fills_gaps(used: set[str], expected: str) -> None:
    """다음 빈 번호는 최댓값+1이 아니라 **가장 작은 미사용 번호**다."""
    sys.path.insert(0, str(CHECKER.parent))
    from adr_number_check import next_free  # noqa: PLC0415

    assert next_free(used) == expected


def test_checker_is_wired_into_ci() -> None:
    """CI harness-integrity 잡이 이 검사를 **실제로 실행**하는가 (acceptance ③).

    "저장소에 존재함"과 "돌아감"은 다르다 — 이 저장소는 그 공백을 세 번 겪었다
    (tests/infra 199건 미실행·브랜치 보호 required check 미강제·tests/infra lint 부재).
    그래서 배선 자체를 계약으로 동결한다.

    문자열 존재만 보지 않고 **같은 잡 안에** 있는지까지 본다: 다른 잡에 붙으면 doc-only PR에서
    skip돼 조용히 무력해질 수 있다.
    """
    ci = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "adr_number_check.py" in ci, "검사기가 CI 어디에도 배선되지 않았다"

    start = ci.index("  harness-integrity:")
    # 다음 최상위 잡(2칸 들여쓰기 + 이름 + 콜론)까지가 이 잡의 범위다.
    rest = ci[start + 1 :]
    match = re.search(r"\n  [a-z][a-z0-9-]*:\n", rest)
    job = rest[: match.start()] if match else rest
    assert (
        "adr_number_check.py" in job
    ), "검사기가 harness-integrity 잡 밖에 배선됐다 — 다른 잡은 경로 필터로 skip될 수 있다"
    # 원격 ref fetch가 선행되지 않으면 스캔이 성립하지 않아 매 실행 exit 1이 된다.
    assert (
        "refs/remotes/origin/*" in job
    ), "전 브랜치 fetch 선행 스텝이 없다 — 스캔이 성립하지 않는다"


# ── PR #1011 리뷰 3건의 회귀 동결 ─────────────────────────────────────────────
# 셋 다 "초판이 조용히 초록을 냈던 상태"를 주입한다. 정상 입력의 초록은 증거가 아니다.


def test_unreadable_advertised_branch_is_red(tmp_path: Path) -> None:
    """원격이 광고한 브랜치를 로컬에서 못 읽으면 통과가 아니라 실패다 (리뷰 P1).

    초판은 이 경우를 빈 목록으로 접어 **부분 스캔을 초록으로** 냈다 — 그리고 그 사실을
    "정직한 공백"에 적어 놓고 배포했다. 여기서는 충돌 ADR을 *못 읽는 브랜치 쪽에* 두어,
    건너뛰면 초록·읽으면 빨강이 되게 한다. 초판이면 이 테스트는 exit 0으로 실패한다.
    """
    up = _init_upstream(tmp_path)
    _branch_with(up, "feat-a", "ADR-002-foo.md")
    _branch_with(up, "feat-b", "ADR-002-bar.md")  # 충돌 상대 — 이 브랜치를 안 보이게 만든다
    work = _clone(tmp_path, up)
    # 광고(ls-remote)는 그대로, 로컬 추적 ref만 지운다 = "fetch 사이에 생긴 브랜치" 재현
    _git(work, "update-ref", "-d", "refs/remotes/origin/feat-b")

    result = _run(work)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "읽지 못했다" in result.stderr
    assert "feat-b" in result.stderr  # 어느 대상이 빠졌는지 지목해야 사람이 고친다


def test_checked_out_head_is_scanned(tmp_path: Path) -> None:
    """체크아웃된 HEAD도 스캔 대상이다 (리뷰 P2).

    fork PR의 merge ref나 아직 push하지 않은 로컬 작업은 원격 브랜치가 아니다. 원격만 보면
    *제안된 바로 그 변경*이 검사에서 빠진다. 여기서는 충돌을 로컬 미푸시 커밋에 둔다 —
    초판이면 원격끼리는 충돌이 없어 exit 0이 된다.
    """
    up = _init_upstream(tmp_path)
    _branch_with(up, "feat-a", "ADR-002-other.md")
    work = _clone(tmp_path, up)
    _git(work, "checkout", "-qb", "local-only")
    _write(work, f"{ADR_DIR}/ADR-002-local.md", "# local\n")
    _git(work, "add", "-A")
    _git(work, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "local")

    result = _run(work)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ADR-002-local.md" in result.stdout
    assert "HEAD" in result.stdout  # 당사자가 "지금 제안된 변경"임이 보여야 한다


def test_number_width_is_normalized(tmp_path: Path) -> None:
    """`ADR-1-x`와 `ADR-001-y`는 같은 번호다 (리뷰 P2).

    초판은 캡처 문자열을 그대로 키로 써서 "1"과 "001"을 다른 번호로 보고 exit 0을 냈다.
    """
    up = _init_upstream(tmp_path)  # main에 ADR-001-alpha
    _branch_with(up, "feat-a", "ADR-1-beta.md")
    work = _clone(tmp_path, up)

    result = _run(work)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ADR-001" in result.stdout
    assert "beta" in result.stdout and "alpha" in result.stdout
