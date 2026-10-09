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


class TestRunLog:
    """PB-10 ③ — 실행마다 구조화 로그 한 줄. no-op이 정상인 현재(응답 0행)를 로그가 말해야 한다."""

    def test_classify_run_separates_three_outcomes(self) -> None:
        """같은 `calibrated_items=0`도 입력 부재·자격 문항 부재·실제 보정은 다른 상태다."""
        no_responses = _report(calibrated_b=0, adopted=0).model_copy(
            update={"items_with_responses": 0}
        )
        below_floor = _report(calibrated_b=0, adopted=0)  # 응답은 있으나 자격 문항 0
        calibrated = _report(calibrated_b=3, adopted=1)
        assert calibrate_items.classify_run(no_responses) == calibrate_items.RUN_NOOP_NO_RESPONSES
        assert (
            calibrate_items.classify_run(below_floor) == calibrate_items.RUN_NOOP_NO_ELIGIBLE_ITEMS
        )
        assert calibrate_items.classify_run(calibrated) == calibrate_items.RUN_CALIBRATED
        assert len({no_responses.items_with_responses, below_floor.items_with_responses}) == 2

    def test_run_log_line_has_run_id_status_and_finished_at(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def _fake_calibrate(session: Any, *, dry_run: bool = False) -> CalibrationReport:
            return _report(dry_run=dry_run, calibrated_b=0, adopted=0).model_copy(
                update={"items_with_responses": 0}
            )

        async def _fake_dispose() -> None:
            return None

        monkeypatch.setattr(calibrate_items, "get_sessionmaker", lambda settings=None: _FakeSession)
        monkeypatch.setattr(calibrate_items, "calibrate_item_difficulties", _fake_calibrate)
        monkeypatch.setattr(calibrate_items, "dispose_engine", _fake_dispose)
        with caplog.at_level("INFO", logger="whymath.l2.calibrate_items"):
            assert calibrate_items.main([]) == 0
        lines = [r.getMessage() for r in caplog.records if r.name == "whymath.l2.calibrate_items"]
        assert len(lines) == 1
        assert lines[0].startswith("calibration_run run_id=")
        assert "status=noop_no_responses" in lines[0]
        assert "items_with_responses=0" in lines[0]
        assert "finished_at=" in lines[0]

    def test_failure_logs_error_type_name_and_reraises(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """실패는 `status=failed error_type=<예외 타입명>`을 남기고 예외를 삼키지 않는다."""
        disposed: dict[str, bool] = {}

        async def _boom(session: Any, *, dry_run: bool = False) -> CalibrationReport:
            raise ConnectionRefusedError("secret-host:5432")

        async def _fake_dispose() -> None:
            disposed["yes"] = True

        monkeypatch.setattr(calibrate_items, "get_sessionmaker", lambda settings=None: _FakeSession)
        monkeypatch.setattr(calibrate_items, "calibrate_item_difficulties", _boom)
        monkeypatch.setattr(calibrate_items, "dispose_engine", _fake_dispose)
        with caplog.at_level("ERROR", logger="whymath.l2.calibrate_items"):
            with pytest.raises(ConnectionRefusedError):
                calibrate_items.main([])
        assert disposed["yes"]  # 실패해도 엔진은 치운다
        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "status=failed" in messages
        assert "error_type=ConnectionRefusedError" in messages
        assert "secret-host" not in messages  # 예외 값은 로그에 싣지 않는다

    def test_text_stdout_contract_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """로그는 stderr 쪽이다 — stdout 첫 줄 하위호환 계약(`calibrated_items=N`)을 건드리지 않는다."""

        async def _fake_calibrate(session: Any, *, dry_run: bool = False) -> CalibrationReport:
            return _report(dry_run=dry_run)

        async def _fake_dispose() -> None:
            return None

        monkeypatch.setattr(calibrate_items, "get_sessionmaker", lambda settings=None: _FakeSession)
        monkeypatch.setattr(calibrate_items, "calibrate_item_difficulties", _fake_calibrate)
        monkeypatch.setattr(calibrate_items, "dispose_engine", _fake_dispose)
        assert calibrate_items.main([]) == 0
        out = capsys.readouterr().out
        assert out.splitlines()[0] == "calibrated_items=3"
        assert "calibration_run" not in out
