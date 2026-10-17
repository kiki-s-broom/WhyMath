"""HARN-170 — 하네스 테스트가 **실제 저장소 대장**에 쓰지 못하게 하는 격리 도구.

`conftest.py`의 두 픽스처가 이 모듈을 쓴다. 테스트 모듈도 직접 임포트해 판정 함수를 단위로
검증한다(`test_real_ledger_isolation.py`). 이름이 `_`로 시작해 pytest가 테스트로 수집하지 않는다.

왜 필요한가
-----------
CLI의 저장소 루트는 **현재 디렉터리의 git 루트**다(`backlog.find_root_for_cli`). pytest는 보통
저장소 루트에서 뜨므로, 임시 저장소로 `chdir`하지 않고 CLI를 부른 테스트는 실제 저장소를
겨눈다. 그때 `check-edit`의 조율 정책 검사가 실제로 발화하면 실제 세션 샤드에 가짜
`policy_warn`을 쓴다. claim이 없는 CI 러너에서는 증상이 없어 CI가 구조적으로 못 잡았고
(사고 대장 계열 `harness-test-live-ledger-write` 15회 · 2026-09-24~28), 세션 종료 훅이 그
줄을 커밋하라고 요구해 main에 같은 서명의 묶음이 쌓였다.

두 겹으로 막는다
----------------
  ① **쓰기 차단**(함수 단위) — `store.append_event`가 실제 루트를 겨누면 기록하지 않고 메모리에
     모은다. 삼키지 않고 모으는 이유: 발화했는지 테스트가 단언할 수 있어야 한다(발화하지 않은
     경로에서 '대장이 그대로'는 아무것도 증명하지 않는다).
  ② **세션 전후 대조**(세션 단위) — `backlog/` 전 파일의 sha256이 실행 전후 같아야 한다.
     ①이 못 막는 경로(직접 파일 쓰기 · 다른 쓰기 함수)를 검출한다. 되돌리지는 않는다 — 실행 중
     사람이 대장을 바꿨을 수도 있어서, 자동 복원은 정당한 기록을 지울 수 있다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR_NAME = "backlog"


def is_real_root(root: object) -> bool:
    """이 경로가 실제 저장소 루트인가 — 경로 해석이 실패하면 아니라고 본다(임시 경로 등)."""
    try:
        return Path(str(root)).resolve() == REPO_ROOT.resolve()
    except OSError:
        return False


def ledger_fingerprint(root: Path = REPO_ROOT) -> dict[str, str]:
    """`backlog/` 전 파일 → sha256. 0건이면 호출측이 실패로 친다(스캔 0건은 통과가 아니다)."""
    base = root / LEDGER_DIR_NAME
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def ledger_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """두 지문의 차이 — 추가·삭제·변경을 한 줄씩(정렬). 빈 목록 = 무변경."""
    changes: list[str] = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            changes.append(f"추가 {name}")
        elif name not in after:
            changes.append(f"삭제 {name}")
        elif before[name] != after[name]:
            changes.append(f"변경 {name}")
    return changes


def guard_session(fingerprint=ledger_fingerprint, fail=None):
    """② 세션 전후 대조의 본체 — conftest의 세션 픽스처가 `yield from`으로 위임한다.

    픽스처 안에 두면 판정 분기를 단위로 시험할 수 없다(세션 픽스처는 직접 부를 수 없다). 그래서
    지문 함수·실패 함수를 받는 평범한 제너레이터로 두고, 테스트는 가짜 지문으로 분기를 밟는다.
    """
    before = fingerprint()
    assert before, "backlog/ 파일을 하나도 못 읽었다 — 전후 대조가 성립하지 않는다(스캔 0건)"
    yield
    changes = ledger_changes(before, fingerprint())
    if changes:
        listed = "\n  ".join(changes[:20])
        message = (
            f"tests/harness 실행 전후로 실제 backlog/ 가 바뀌었다 {len(changes)}건 (HARN-170):"
            f"\n  {listed}\n테스트가 실제 저장소 대장에 썼거나, 실행 도중 트리가 바뀌었다."
        )
        if fail is None:
            raise AssertionError(message)
        fail(message)
