"""헌법 토큰 실측 스크립트의 브리핑 수집 인코딩 계약 (HARN-169).

한국어 Windows(cp949)에서는 파이프로 연결된 자식 파이썬의 stdout이 로케일 인코딩이 되어,
브리핑의 `—`·`⚠` 같은 문자에서 UnicodeEncodeError로 exit 1이 난다. 그러면 브리핑이
'미측정'으로 떨어지고 합계가 하한이 된다 — 게이트 G-harn121의 측정 1회가 공전한다.
여기서는 부모 환경을 cp949로 강제해 그 조건을 이 컨테이너에서 재현한다.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "measure_constitution_tokens.py"


def _load():
    spec = importlib.util.spec_from_file_location("measure_constitution_tokens", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_brief_collected_even_when_parent_env_is_cp949(monkeypatch: pytest.MonkeyPatch) -> None:
    # 한국어 Windows의 파이프 stdout 조건을 재현 — 자식이 이 환경을 그대로 물려받는다
    monkeypatch.setenv("PYTHONIOENCODING", "cp949")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    text, error = _load()._brief_text(ROOT)
    assert error is None, error
    assert "[빌드하네스 브리핑]" in text


def test_decode_error_becomes_unmeasured_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    # 자식이 UTF-8이 아닌 바이트를 내도 크래시하지 않고 사유로 남긴다(측정 실패가 보여야 한다)
    mod = _load()

    def fake_run(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xb0", 0, 1, "invalid start byte")

    monkeypatch.setattr(subprocess, "run", fake_run)
    text, error = mod._brief_text(ROOT)
    assert text == ""
    assert error is not None and "UnicodeDecodeError" in error


def test_script_refuses_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # 키 없으면 문자 수로 대체하지 않고 exit 2 — 기존 계약 동결
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _load().main([]) == 2


def test_script_is_importable_by_path() -> None:
    assert SCRIPT.is_file()
    assert sys.executable
