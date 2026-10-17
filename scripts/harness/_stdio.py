"""CLI 진입점의 stdout/stderr을 UTF-8로 맞춘다 (OPS-53).

왜 필요한가
-----------
한국어 Windows에서 파이프·리다이렉트(`| Tee-Object`, `> file`)의 stdout/stderr은 로캘
인코딩(cp949)을 쓴다. 콘솔은 별도 경로(WriteConsoleW)라 멀쩡해 보여서 결함이 가려진다.
cp949에 없는 글자(— U+2014, ⏳ U+23F3 등)를 print하면 UnicodeEncodeError로 CLI가 죽고,
출력이 잘린 채 종료 코드가 1이 된다.

해법 선택(acceptance ⑤): '문자 금지'가 아니라 진입점에서 스트림을 UTF-8로 재구성한다.
docs/ops/windows_utf8_setup.md §1 — 애플리케이션 내부에서 CP949를 지원하려 하지 않는다.

stdlib만 쓴다(빌드 하네스는 백엔드 패키지에 의존하지 않는다). 같은 동작의 사본이
src/backend/whymath_backend/_stdio.py에 있다 — 두 사본의 일치는
tests/harness/test_cli_stdio_utf8.py가 동결한다.
"""

from __future__ import annotations

import sys

_UTF8_ALIASES = {"utf8", "u8"}  # 하이픈·밑줄을 지운 뒤의 UTF-8 별칭


def ensure_utf8_stdio() -> None:
    """stdout·stderr이 UTF-8이 아니면 UTF-8로 다시 설정한다. 이미 UTF-8이면 아무것도 안 한다.

    인코딩은 UTF-8로 바꾸되 errors는 backslashreplace — 짝 없는 surrogate 같은 예외적 입력에도
    출력이 죽지 않는다. 재구성에 실패하면 침묵하지 않고 예외 타입명만 stderr에 남긴다(값은 제외).
    reconfigure가 없는 스트림(pytest 캡처 객체 등)은 건드리지 않는다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        name = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if name in _UTF8_ALIASES:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError) as exc:
            try:
                msg = f"경고: 출력 인코딩 UTF-8 설정 실패({type(exc).__name__})"
                print(msg, file=sys.__stderr__)
            except (ValueError, OSError):
                pass  # 경고조차 못 쓰는 상태 — 더 할 수 있는 일이 없다
