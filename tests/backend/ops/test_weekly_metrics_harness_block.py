"""HARN-118 ③ — 주간 원장의 하네스 지표 3종(사고 건수·계열 최대 회차·산문만 대책 비율).

이 파일이 지키는 계약은 둘이다:
  ① **미측정 ≠ 0** — 사고 요약이 없거나 깨졌을 때 3종이 0으로 나오면 안 된다.
     원장을 읽는 쪽이 "사고 0건"으로 오독하면 지표가 거짓말이 된다.
  ② **기존 6종 불변** — `KPI_NAMES`는 EOS-51 §6이 동결한 6종이고 하네스 지표는
     별개 블록이다. 이 파일이 6종에 7번째를 만들지 않았음을 함께 동결한다.

hermetic — DB 불요·파일시스템은 tmp_path만 쓴다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whymath_backend.ops.weekly_metrics_report import (
    HARNESS_METRIC_NAMES,
    KPI_NAMES,
    build_harness_metrics,
    build_record_from_report,
    load_incidents_summary,
)

_SUMMARY = {
    "total": 676,
    "max_series_nth": 13,
    "rule_only_ratio": 0.1065,
    "by_cat": {"B": 177},
}


def _record(harness: dict | None):
    now = datetime(2026, 9, 21, tzinfo=UTC)
    return build_record_from_report(
        None,
        week_start=now,
        week_end=now,
        generated_at=now,
        krw_per_usd=None,
        db_failure_reason="테스트",
        harness=harness,
    )


class TestHarnessMetricsAreSeparateFromTheSixKpis:
    def test_kpi_names_still_holds_exactly_six(self) -> None:
        """7번째 KPI를 지어내지 않았다 — 이 모듈의 오래된 계약(2026-09-11 표기 정정)."""
        assert len(KPI_NAMES) == 6
        assert not set(HARNESS_METRIC_NAMES) & set(KPI_NAMES)

    def test_record_carries_both_blocks(self) -> None:
        payload = _record(build_harness_metrics(_SUMMARY)).to_json()
        assert set(payload["kpis"]) == set(KPI_NAMES)
        assert set(payload["harness"]) == set(HARNESS_METRIC_NAMES)


class TestMeasuredPath:
    def test_three_metrics_come_from_the_summary(self) -> None:
        metrics = build_harness_metrics(_SUMMARY)
        assert metrics["incident_count"].value == 676.0
        assert metrics["max_series_nth"].value == 13.0
        assert metrics["rule_only_fix_ratio"].value == pytest.approx(0.1065)
        assert all(m.measured for m in metrics.values())

    def test_units_are_explicit(self) -> None:
        metrics = build_harness_metrics(_SUMMARY)
        assert metrics["incident_count"].unit == "count"
        assert metrics["rule_only_fix_ratio"].unit == "ratio"


class TestUnmeasuredIsNotZero:
    """핵심 변별력 — 수집 실패가 '0'으로 위장되면 안 된다."""

    def test_missing_summary_yields_unmeasured_not_zero(self) -> None:
        metrics = build_harness_metrics(None, failure_reason="사고 요약 파일 없음: /x")
        assert set(metrics) == set(HARNESS_METRIC_NAMES)
        for name, kpi in metrics.items():
            assert kpi.measured is False, name
            assert kpi.value is None, f"{name}이 0으로 위장됐다"
            assert "없음" in (kpi.reason or "")

    def test_record_without_harness_argument_still_has_three_unmeasured_keys(self) -> None:
        """인자를 아예 안 넘겨도 키는 3개다 — 빈 dict면 '안 쟀다'와 '못 쟀다'가 같아진다."""
        payload = _record(None).to_json()
        assert set(payload["harness"]) == set(HARNESS_METRIC_NAMES)
        assert all(
            v["measured"] is False and v["value"] is None for v in payload["harness"].values()
        )

    @pytest.mark.parametrize("bad", [None, "676", True, {"n": 1}, [1]])
    def test_non_numeric_value_is_unmeasured_per_metric(self, bad: object) -> None:
        """한 키가 깨져도 **그 지표만** 미측정 — 나머지를 버리지도, 0으로 채우지도 않는다."""
        metrics = build_harness_metrics({**_SUMMARY, "total": bad})
        assert metrics["incident_count"].measured is False
        assert metrics["incident_count"].value is None
        assert metrics["max_series_nth"].measured is True

    def test_bool_is_not_accepted_as_a_count(self) -> None:
        """`True`는 파이썬에서 int지만 사고 건수가 아니다 — 1건으로 계상되면 거짓 측정이다."""
        metrics = build_harness_metrics({**_SUMMARY, "total": True})
        assert metrics["incident_count"].measured is False


class TestLoadIncidentsSummary:
    def test_none_path_reports_why(self) -> None:
        summary, reason = load_incidents_summary(None)
        assert summary is None
        assert reason and "--incidents-summary" in reason

    def test_missing_file_reports_the_path(self, tmp_path: Path) -> None:
        summary, reason = load_incidents_summary(tmp_path / "nope.json")
        assert summary is None
        assert reason and "nope.json" in reason

    def test_corrupt_json_names_the_exception_type(self, tmp_path: Path) -> None:
        """침묵 실패 금지 — 예외 타입명이 사유에 포함돼야 한다(CLAUDE.md)."""
        path = tmp_path / "s.json"
        path.write_text("{not json", encoding="utf-8")
        summary, reason = load_incidents_summary(path)
        assert summary is None
        assert reason and "JSONDecodeError" in reason

    def test_non_object_payload_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        summary, reason = load_incidents_summary(path)
        assert summary is None
        assert reason and "list" in reason

    def test_valid_payload_round_trips(self, tmp_path: Path) -> None:
        """대조군 — 정상 입력이 통과하지 않으면 위 거부들은 변별력이 없다."""
        path = tmp_path / "s.json"
        path.write_text(json.dumps(_SUMMARY, ensure_ascii=False), encoding="utf-8")
        summary, reason = load_incidents_summary(path)
        assert reason is None
        assert summary == _SUMMARY
