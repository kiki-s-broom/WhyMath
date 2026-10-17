"""R2-04 (제9조 · 판례 P0001) 도장 찍기 조기 경보 — scripts/constitution/review_health.py 계약 동결."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "constitution" / "review_health.py"
SID = "11111111-1111-1111-1111-111111111111"


def _ev(
    sid: str = SID,
    *,
    ms: int | None = 30_000,
    verdict: str = "approved",
    typ: str = "finished",
) -> dict[str, object]:
    return {
        "review_session_id": sid,
        "event_type": typ,
        "verdict": verdict if typ == "finished" else None,
        "elapsed_ms": ms,
    }


def _run(
    tmp_path: Path, rows: list[object], *extra: str, raw: bytes | None = None
) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "ev.jsonl"
    path.write_bytes(
        raw
        if raw is not None
        else ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode()
    )
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--events", str(path), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _healthy() -> list[dict[str, object]]:
    return [_ev(ms=30_000, verdict="rejected" if i == 0 else "approved") for i in range(6)]


def test_healthy_session_has_no_warning(tmp_path: Path) -> None:
    res = _run(tmp_path, _healthy(), "--strict")
    assert res.returncode == 0, res.stderr
    assert "경고 없음" in res.stdout


def test_fast_median_warns(tmp_path: Path) -> None:
    """P0001 재현 — 중앙값 3초."""
    rows = [_ev(ms=3_000, verdict="rejected" if i == 0 else "approved") for i in range(6)]
    res = _run(tmp_path, rows)
    assert res.returncode == 0  # L4 는 경고 — 기본은 통과 코드
    assert "중앙값 3.0초" in res.stderr
    assert _run(tmp_path, rows, "--strict").returncode == 1


def test_median_exactly_ten_seconds_is_not_warned(tmp_path: Path) -> None:
    """경계 — 규칙은 '10초 미만'이다. 정확히 10초는 경고가 아니다."""
    rows = [_ev(ms=10_000, verdict="rejected" if i == 0 else "approved") for i in range(6)]
    assert _run(tmp_path, rows, "--strict").returncode == 0


def test_zero_reject_rate_warns(tmp_path: Path) -> None:
    rows = [_ev(ms=30_000) for _ in range(6)]
    res = _run(tmp_path, rows, "--strict")
    assert res.returncode == 1
    assert "반려율 0%" in res.stderr


def test_approved_with_edit_is_not_a_rejection(tmp_path: Path) -> None:
    rows = [_ev(ms=30_000, verdict="approved_with_edit") for _ in range(6)]
    assert _run(tmp_path, rows, "--strict").returncode == 1


def test_small_sample_is_deferred_not_warned_nor_passed(tmp_path: Path) -> None:
    rows = [_ev(ms=1_000) for _ in range(4)]  # 4건 — 빠르고 반려 0 이지만 표본 부족
    res = _run(tmp_path, rows, "--strict")
    assert res.returncode == 0
    assert "판정 보류" in res.stdout
    assert "경고 없음" not in res.stdout  # 보류를 '통과'로 위장하지 않는다


def test_unmeasured_elapsed_is_not_counted_as_zero(tmp_path: Path) -> None:
    """elapsed_ms=null 을 0초로 날조하면 중앙값 경보가 거짓으로 터진다."""
    rows = [_ev(ms=None, verdict="rejected" if i == 0 else "approved") for i in range(6)]
    res = _run(tmp_path, rows, "--strict")
    assert res.returncode == 0
    assert "시간 경보 보류" in res.stdout


def test_sessions_are_judged_separately(tmp_path: Path) -> None:
    other = "22222222-2222-2222-2222-222222222222"
    rows = _healthy() + [_ev(other, ms=2_000) for _ in range(6)]
    res = _run(tmp_path, rows, "--strict")
    assert res.returncode == 1
    assert other in res.stderr
    assert SID not in res.stderr


def test_non_finished_events_are_ignored(tmp_path: Path) -> None:
    rows = _healthy() + [_ev(typ="started"), _ev(typ="aborted")]
    assert _run(tmp_path, rows, "--strict").returncode == 0


def test_missing_events_arg_is_measure_failure() -> None:
    res = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={"PATH": __import__("os").environ["PATH"]},
    )
    assert res.returncode == 2
    assert "측정 불가" in res.stderr


def test_missing_file_is_measure_failure(tmp_path: Path) -> None:
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--events", str(tmp_path / "nope.jsonl")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 2


def test_empty_and_started_only_are_measure_failure(tmp_path: Path) -> None:
    assert _run(tmp_path, [], raw=b"").returncode == 2
    assert _run(tmp_path, [_ev(typ="started")]).returncode == 2


def test_all_garbage_is_measure_failure(tmp_path: Path) -> None:
    res = _run(tmp_path, [], raw=b"not json\n{broken\n")
    assert res.returncode == 2
    assert "파싱 전멸" in res.stderr


def test_non_utf8_is_measure_failure(tmp_path: Path) -> None:
    assert _run(tmp_path, [], raw="한글".encode("cp949")).returncode == 2


def test_some_bad_lines_are_reported_but_rest_judged(tmp_path: Path) -> None:
    good = "\n".join(json.dumps(r) for r in _healthy()).encode()
    res = _run(tmp_path, [], "--strict", raw=good + b"\n{broken\n")
    assert res.returncode == 0
    assert "해석 실패 1행" in res.stderr
    assert "JSONDecodeError" in res.stderr  # 예외 타입명 보존


@pytest.mark.parametrize("bad_ms", [-5, "30", True])
def test_invalid_elapsed_values_are_unmeasured(tmp_path: Path, bad_ms: object) -> None:
    rows = [_ev(ms=bad_ms, verdict="rejected" if i == 0 else "approved") for i in range(6)]  # type: ignore[arg-type]
    res = _run(tmp_path, rows, "--strict")
    assert res.returncode == 0
    assert "시간 경보 보류" in res.stdout


def test_median_not_mean_decides(tmp_path: Path) -> None:
    """평균이 아니라 중앙값 — 느린 몇 건이 평균을 끌어올려도 중앙값 경보는 유지된다(반대도 성립)."""
    skew_up = [2, 2, 2, 2, 100, 100]  # 중앙값 2초(경고), 평균 34초
    rows = [
        _ev(ms=s * 1000, verdict="rejected" if i == 0 else "approved")
        for i, s in enumerate(skew_up)
    ]
    assert _run(tmp_path, rows, "--strict").returncode == 1
    skew_down = [0.1, 0.1, 15, 15, 15, 15]  # 중앙값 15초(정상), 평균 ≈ 8.4초
    rows = [
        _ev(ms=int(s * 1000), verdict="rejected" if i == 0 else "approved")
        for i, s in enumerate(skew_down)
    ]
    assert _run(tmp_path, rows, "--strict").returncode == 0
