"""`scripts/ops/phase3_metrics_readonly.py` — 운영 DB 실측용 읽기 전용 실행기 동결 (P3-106).

이 실행기가 막으려는 상태는 "측정 중 운영 DB에 쓰기"다. 정상 입력에서 초록인 것은 보호의
증거가 아니므로 막으려는 상태(UPDATE)를 실제로 주입해 차단을 확인하고, 같은 주입이 보호 없는
엔진에서는 성공함(대조군)을 함께 본다 — 대조군이 없으면 "어차피 실패하는 주입"과 구별이 안 된다.

실 PG가 필요하다(`integration` 마커 · CI `backend — 마이그레이션·통합 (실 PG)` 잡이 수집).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "ops" / "phase3_metrics_readonly.py"
_INJECT = "UPDATE learning_session SET started_at = started_at"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("phase3_metrics_readonly", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _try_write() -> str:
    """현재 전역 엔진으로 UPDATE를 시도 — 'ok' 또는 예외 타입명(롤백해 흔적을 남기지 않는다)."""
    from sqlalchemy import text

    from whymath_backend.db.session import dispose_engine, get_engine

    try:
        async with get_engine().connect() as conn:
            try:
                await conn.execute(text(_INJECT))
                return "ok"
            except Exception as exc:  # noqa: BLE001 - 차단 여부만 본다
                return type(exc).__name__ + ":" + str(exc)
            finally:
                await conn.rollback()
    finally:
        await dispose_engine()


def test_injected_write_is_blocked_by_read_only_engine() -> None:
    """주입(RED 축): 실행기의 엔진에서 UPDATE는 DB가 거부해야 한다."""
    _load().install_read_only_engine()
    result = asyncio.run(_try_write())
    assert result != "ok", "읽기 전용 엔진에서 UPDATE가 성공했다 — 보호가 걸리지 않았다."
    assert "read-only transaction" in result, f"다른 이유로 실패했다(판정 불가): {result[:200]}"


def test_same_write_succeeds_without_protection() -> None:
    """대조군: 같은 UPDATE가 보호 없는 기본 엔진에서는 성공해야 위 차단이 의미를 갖는다."""
    result = asyncio.run(_try_write())
    assert result == "ok", f"대조군 UPDATE가 실패했다 — 주입 자체가 무효: {result[:200]}"


def test_self_check_refuses_when_read_only_is_not_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """자가확인의 변별력: 접속이 읽기 전용이 아니면 측정하지 않고 exit 3으로 거부한다."""
    module = _load()
    monkeypatch.setattr(
        module, "READ_ONLY_SERVER_SETTINGS", {"default_transaction_read_only": "off"}
    )
    try:
        assert module.main(["--no-db"]) == module.EXIT_REFUSED
    finally:
        from whymath_backend.db.session import dispose_engine

        asyncio.run(dispose_engine())


def test_runner_reports_read_only_and_runs_metrics(tmp_path: Path) -> None:
    """정상 경로(GREEN 축): 별도 프로세스로 돌면 READ_ONLY=True·CODE_FILE을 내고 판정 JSON을 쓴다."""
    out = tmp_path / "p3.json"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--json", str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ),
        timeout=600,
        check=False,
    )
    # phase3_metrics 계약: 0·1·2 는 판정, 3 은 실행 오류. 3 이면 실행기 자체가 실패한 것이다.
    assert proc.returncode in (0, 1, 2), proc.stderr[-2000:]
    assert "READ_ONLY=True" in proc.stdout, proc.stdout[-2000:]
    assert "CODE_FILE=" in proc.stdout
    assert out.exists() and '"learning_loop_success"' in out.read_text(encoding="utf-8")
    # 회신 줄: ASCII 한 줄이어야 cp949 콘솔을 거쳐도 깨지지 않는다.
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("P5_SUMMARY=")]
    assert len(lines) == 1, proc.stdout[-2000:]
    assert lines[0].isascii()
    summary = json.loads(lines[0].removeprefix("P5_SUMMARY="))
    assert summary["exit_code"] == proc.returncode
    assert summary["state"] in ("measured", "unmeasured")
