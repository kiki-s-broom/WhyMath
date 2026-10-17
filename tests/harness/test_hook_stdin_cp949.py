"""HARN-196 — 훅 진입점(`check-stop`·`check-edit`·`audit.py --hook`)이 cp949 로캘에서도 UTF-8 입력을 읽는다.

**재현 방식**: 서브프로세스에 `PYTHONIOENCODING=cp949` 를 주면 `sys.stdin` 이 한국어 Windows 처럼
cp949 로 해독한다. 페이로드는 반드시 `ensure_ascii=False` 로 직렬화한 **UTF-8 원문**이어야 한다 —
기본값(`True`)은 한글과 '—' 를 전부 `\\uXXXX` 로 바꿔 순수 ASCII 로 만들어, 로캘 해독 결함이 있는
코드도 통과시킨다(CONST-10 이 실측한 기존 테스트의 맹점). 아래 `_PAYLOAD_NOTE` 가 그 비ASCII 부분이다.

수정 전 동작(이 테스트가 RED 였던 이유)
- `check-stop`·`check-edit`: `UnicodeDecodeError` 가 `except json.JSONDecodeError` 에 안 걸려 훅이
  트레이스백으로 죽는다(exit 1 — fail-open 이 아니라 **미작동**).
- `audit.py --hook`: `ValueError` 를 삼키고 `stop_hook_active` 를 잃어 Stop 훅 재진입 방지가 꺼진다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKLOG = _REPO_ROOT / "scripts" / "harness" / "backlog.py"
_AUDIT = _REPO_ROOT / "scripts" / "constitution" / "audit.py"

# UTF-8 로 E2 80 94(—) + 한글 — cp949 로 읽으면 깨지는 바이트 열
_PAYLOAD_NOTE = "설명 — 한글 포함"


def _run(argv: list[str], payload: dict) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "PYTHONIOENCODING": "cp949"}
    env.pop("PYTHONUTF8", None)  # UTF-8 모드가 켜져 있으면 PYTHONIOENCODING 이 무력화된다
    return subprocess.run(  # noqa: S603 — 고정 인자
        [sys.executable, *argv],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        cwd=_REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )


def test_payload_really_is_non_ascii() -> None:
    """픽스처 변별력 — 직렬화 결과가 순수 ASCII 면 이 파일 전체가 위장이다."""
    raw = json.dumps({"n": _PAYLOAD_NOTE}, ensure_ascii=False).encode("utf-8")
    assert b"\xe2\x80\x94" in raw
    with pytest.raises(UnicodeDecodeError):
        raw.decode("cp949")


def test_check_stop_survives_cp949_locale() -> None:
    result = _run([str(_BACKLOG), "check-stop"], {"stop_hook_active": True, "note": _PAYLOAD_NOTE})
    assert b"Traceback" not in result.stderr, result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0  # stop_hook_active 를 읽어 즉시 통과


def test_check_edit_survives_cp949_locale(tmp_path: Path) -> None:
    outside = tmp_path / f"{_PAYLOAD_NOTE}.py"  # 레포 밖 — 대장에 아무것도 쓰지 않는다
    result = _run([str(_BACKLOG), "check-edit"], {"tool_input": {"file_path": str(outside)}})
    assert b"Traceback" not in result.stderr, result.stderr.decode("utf-8", "replace")
    assert b"UnicodeDecodeError" not in result.stderr
    assert result.returncode == 0


def test_audit_hook_keeps_stop_hook_active_under_cp949() -> None:
    """재진입 방지가 살아 있으면 심사를 돌리지 않고 즉시 0 — 출력이 비어 있다."""
    pytest.importorskip("yaml")  # audit.py 는 모듈 임포트 시점에 pyyaml 을 요구한다(CI 에는 있다)
    result = _run(
        [str(_AUDIT), "--hook", "--sources-only", "--no-run"],
        {"stop_hook_active": True, "note": _PAYLOAD_NOTE},
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout == b"", "stop_hook_active 를 잃고 심사를 끝까지 돌렸다"


def test_harness_stdin_double_has_a_byte_layer_and_cp949_text_layer() -> None:
    """공용 대역의 구조 — `.buffer` 가 있고 텍스트 계층은 cp949 라 `.read()` 회귀를 드러낸다."""
    from _hook_stdin import set_hook_stdin

    mp = pytest.MonkeyPatch()
    try:
        set_hook_stdin(mp, json.dumps({"n": _PAYLOAD_NOTE}, ensure_ascii=False))
        assert sys.stdin.buffer.read().decode("utf-8")
        mp.undo()
        set_hook_stdin(mp, json.dumps({"n": _PAYLOAD_NOTE}, ensure_ascii=False))
        with pytest.raises(UnicodeDecodeError):
            sys.stdin.read()
    finally:
        mp.undo()
