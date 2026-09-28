"""L2 보정 배치 CLI — `calibrate_items` 단위테스트 (hermetic·monkeypatch).

slice 80: CLI 글루(`_run`: 세션 획득 → `calibrate_item_difficulties` → 엔진 정리 → 리포트)와
`main`(argparse + asyncio.run)을 DB 없이 검증한다. 보정 로직 자체는 slice 79
`test_item_calibration`·실 PG 통합테스트가 가드 — 여기선 진입점 배선(세션 수명·리포트)만 본다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from whymath_backend.l2 import calibrate_items
from whymath_backend.l2.item_calibration import (
    FALLBACK_REASONS,
    RESPONSE_COUNT_BUCKETS,
    CalibrationReport,
)


def _report(*, dry_run: bool = False, calibrated_b: int = 3, adopted: int = 1) -> CalibrationReport:
    reasons = dict.fromkeys(FALLBACK_REASONS, 0)
    reasons["insufficient_responses"] = calibrated_b - adopted
    return CalibrationReport(
        dry_run=dry_run,
        items_with_responses=calibrated_b + 2,
        calibrated_b=calibrated_b,
        discrimination_calibrated=adopted,
        discrimination_fallback=calibrated_b - adopted,
        fallback_reasons=reasons,
        response_count_distribution=dict.fromkeys(RESPONSE_COUNT_BUCKETS, 1),
        boundary_theta_responses_excluded=4,
    )


class _FakeSession:
    """async 컨텍스트 매니저 세션 스텁(calibrate가 페이크라 세션 내용은 무관)."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class TestCli:
    def test_main_help_exits_zero(self) -> None:
        """--help → argparse가 SystemExit(0)."""
        with pytest.raises(SystemExit) as exc_info:
            calibrate_items.main(["--help"])
        assert exc_info.value.code == 0

    def test_main_runs_calibration_reports_and_disposes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main → 세션 1개로 보정 실행·보정 수 리포트·엔진 정리·종료 0."""
        disposed: dict[str, bool] = {}

        async def _fake_calibrate(session: Any, *, dry_run: bool = False) -> CalibrationReport:
            return _report(dry_run=dry_run)

        async def _fake_dispose() -> None:
            disposed["yes"] = True

        # get_sessionmaker는 호출 시 async-CM 세션을 주는 팩토리(_FakeSession 클래스)를 반환.
        monkeypatch.setattr(calibrate_items, "get_sessionmaker", lambda settings=None: _FakeSession)
        monkeypatch.setattr(calibrate_items, "calibrate_item_difficulties", _fake_calibrate)
        monkeypatch.setattr(calibrate_items, "dispose_engine", _fake_dispose)

        assert calibrate_items.main([]) == 0
        assert disposed["yes"]  # 배치 종료 시 엔진 풀 정리
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "calibrated_items=3"  # 첫 줄 하위호환 고정
        assert "dry_run=false" in out
        assert "discrimination_fallback_ratio=0.6667" in out
        assert "fallback_reason.insufficient_responses=2" in out
        assert "response_count_bucket.100+=1" in out

    def _patch(self, monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]) -> None:
        async def _fake_calibrate(session: Any, *, dry_run: bool = False) -> CalibrationReport:
            seen["dry_run"] = dry_run
            return _report(dry_run=dry_run)

        async def _fake_dispose() -> None:
            return None

        monkeypatch.setattr(calibrate_items, "get_sessionmaker", lambda settings=None: _FakeSession)
        monkeypatch.setattr(calibrate_items, "calibrate_item_difficulties", _fake_calibrate)
        monkeypatch.setattr(calibrate_items, "dispose_engine", _fake_dispose)

    def test_dry_run_flag_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """EOS-129 ⑤ — `--dry-run`이 보정 함수까지 전달돼야 읽기 전용 측정이 성립한다."""
        seen: dict[str, Any] = {}
        self._patch(monkeypatch, seen)
        assert calibrate_items.main(["--dry-run"]) == 0
        assert seen["dry_run"] is True
        assert "dry_run=true" in capsys.readouterr().out.splitlines()

    def test_default_is_not_dry_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}
        self._patch(monkeypatch, seen)
        assert calibrate_items.main([]) == 0
        assert seen["dry_run"] is False

    def test_json_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seen: dict[str, Any] = {}
        self._patch(monkeypatch, seen)
        assert calibrate_items.main(["--dry-run", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert payload["calibrated_b"] == 3
        assert payload["discrimination_fallback_ratio"] == pytest.approx(2 / 3)


class TestReportFormatting:
    def test_ratio_none_is_printed_as_none_not_zero(self) -> None:
        """분모 0이면 'none' — 0.0000으로 찍으면 "측정 대상 없음"이 "전부 작동"으로 읽힌다."""
        lines = calibrate_items.format_report_lines(_report(calibrated_b=0, adopted=0))
        assert lines[0] == "calibrated_items=0"
        assert "discrimination_fallback_ratio=none" in lines
        assert (
            calibrate_items.report_to_dict(_report(calibrated_b=0, adopted=0))[
                "discrimination_fallback_ratio"
            ]
            is None
        )
