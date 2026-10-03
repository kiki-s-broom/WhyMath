"""훅 stdin 테스트 대역 (HARN-196).

`io.StringIO` 는 `.buffer` 가 없어, 훅 입력을 바이트로 읽는 `check-edit`·`check-stop` 에 쓸 수 없다.
이 대역은 실제 stdin 과 같은 구조다 — 바이트 계층(`.buffer`) 위에 **로캘 인코딩(cp949) 텍스트
래퍼**를 얹는다. 그래서 코드가 `sys.stdin.read()` 로 되돌아가면 비ASCII 페이로드에서 실제
환경처럼 `UnicodeDecodeError` 가 난다(대역이 결함을 가리지 않는다).
"""

from __future__ import annotations

import io

import pytest


def set_hook_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """`sys.stdin` 을 UTF-8 바이트 `text` 를 담은 cp949 텍스트 래퍼로 바꾼다."""
    wrapper = io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="cp949")
    monkeypatch.setattr("sys.stdin", wrapper)
