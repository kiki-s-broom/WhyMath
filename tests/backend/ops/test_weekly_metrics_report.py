"""주간 KPI 집계기(OPS-56) — 순수 로직·미측정≠0·파일 원장 append.

정본: `ops/weekly_metrics_report.py`. hermetic(DB 불요) — 실 PG 왕복은
`test_weekly_metrics_report_integration.py`(기본 skip)가 담당한다.

검증 축:
  - KPI_NAMES가 정확히 6종(EOS-51 §6 "기술 KPI 6종") — "7지표" 표기를 그대로 구현하지
    않았음을 실측 고정.
  - 자동검증 1차 통과율·재작업률은 데이터가 있어도(HitCuReport가 채워져 있어도) 항상
    미측정 — 구조적 부재는 DB 성패와 무관하다.
  - HIT·처리량·단위비용·실패분포는 표본이 있으면 measured=True·수치 실재, 표본 0이면
    measured=False·value=None(0으로 위장 금지).
  - DB 실패(`report=None`)면 그 4종 전부 미측정으로 강등되고 사유에 예외 타입명이 남는다.
  - `append_record`는 기존 원장을 보존한 채 새 행만 더한다(덮어쓰기 금지) — 파일 없음은
    빈 배열로 시작.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from whymath_backend.harness.review_timer import finish_review, start_review
from whymath_backend.ops.hit_cu_metrics import HitCuReport, aggregate
from whymath_backend.ops.weekly_metrics_report import (
    KPI_NAMES,
    STRUCTURALLY_UNMEASURED,
    append_record,
    build_record_from_report,
    collect,
    load_ledger,
)
from whymath_backend.schema.enums import GenerationFailureCode

_T0 = datetime(2026, 9, 1, tzinfo=UTC)
_WEEK_START = datetime(2026, 9, 1, tzinfo=UTC)
_WEEK_END = datetime(2026, 9, 8, tzinfo=UTC)
_GENERATED_AT = datetime(2026, 9, 8, 1, 0, tzinfo=UTC)


def _reviewed_cu(
    slug: str,
    elapsed_ms: int | None,
    *,
    verdict: str = "approved",
    failure_code: GenerationFailureCode | None = None,
    problem_id: uuid.UUID | None = None,
) -> list:
    started = start_review(cu_slug=slug, reviewer_id="kiki", problem_id=problem_id, occurred_at=_T0)
    finished = finish_review(
        review_session_id=started.review_session_id,
        cu_slug=slug,
        reviewer_id="kiki",
        verdict=verdict,  # type: ignore[arg-type]
        failure_code=failure_code,
        elapsed_ms=elapsed_ms,
        problem_id=problem_id,
        occurred_at=_T0,
    )
    return [started, finished]


def _empty_report() -> HitCuReport:
    return aggregate([])


class TestKpiNamesMatchFrozenSix:
    def test_exactly_six_kpi_names(self) -> None:
        """[acceptance①] EOS-51 §6은 "기술 KPI 6종"이다 — 7번째를 지어내지 않는다."""
        assert len(KPI_NAMES) == 6

    def test_structurally_unmeasured_is_subset_of_kpi_names(self) -> None:
        assert set(STRUCTURALLY_UNMEASURED).issubset(set(KPI_NAMES))
        assert set(STRUCTURALLY_UNMEASURED) == {"auto_gate_pass_rate", "rework_rate"}


class TestBuildRecordStructurallyUnmeasured:
    def test_auto_gate_and_rework_always_unmeasured_even_with_rich_data(self) -> None:
        """[acceptance②] 나머지 4종이 전부 measured여도 이 2종은 항상 미측정이다."""
        events = _reviewed_cu("cu-a", 60_000)
        report = aggregate(
            events,
            genlog_rows=[
                {"problem_id": None, "cost_usd": 1.0, "input_tokens": 100, "output_tokens": 50}
            ],
        )
        record = build_record_from_report(
            report,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=1400,
        )
        assert record.kpis["auto_gate_pass_rate"].measured is False
        assert record.kpis["auto_gate_pass_rate"].value is None
        assert record.kpis["rework_rate"].measured is False
        assert record.kpis["rework_rate"].value is None


class TestBuildRecordEmptyReportIsUnmeasuredNotZero:
    def test_empty_report_all_four_dynamic_kpis_unmeasured(self) -> None:
        """[acceptance②] 표본 0건은 "0"이 아니라 미측정 — 0으로 위장 금지."""
        record = build_record_from_report(
            _empty_report(),
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=1400,
        )
        for name in (
            "hit_seconds",
            "throughput_cu_per_hour",
            "unit_cost_krw",
            "failure_type_distribution",
        ):
            assert record.kpis[name].measured is False, name
            assert record.kpis[name].value is None, name
            assert record.kpis[name].reason  # 사유 비어있지 않음

    def test_all_six_kpis_present_in_output(self) -> None:
        record = build_record_from_report(
            _empty_report(),
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=1400,
        )
        assert set(record.kpis) == set(KPI_NAMES)


class TestBuildRecordMeasuredValues:
    def test_hit_and_throughput_measured_from_real_sample(self) -> None:
        events = _reviewed_cu("cu-a", 60_000) + _reviewed_cu("cu-b", 120_000)
        report = aggregate(events)
        record = build_record_from_report(
            report,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=None,
        )
        hit = record.kpis["hit_seconds"]
        assert hit.measured is True
        assert hit.value == pytest.approx(90.0)  # 중앙값(60s, 120s)

        throughput = record.kpis["throughput_cu_per_hour"]
        assert throughput.measured is True
        # 2 CU / (180초/3600) = 40 CU/h
        assert throughput.value == pytest.approx(40.0)

    def test_unit_cost_measured_with_krw_rate(self) -> None:
        pid = uuid.uuid4()
        events = _reviewed_cu("cu-a", 60_000, problem_id=pid)
        report = aggregate(
            events,
            genlog_rows=[
                {
                    "problem_id": str(pid),
                    "cost_usd": 0.5,
                    "input_tokens": 1000,
                    "output_tokens": 200,
                }
            ],
        )
        record = build_record_from_report(
            report,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=1400.0,
        )
        cost = record.kpis["unit_cost_krw"]
        assert cost.measured is True
        assert cost.value == pytest.approx(0.5 * 1400.0 / 1)

    def test_unit_cost_unmeasured_without_krw_rate(self) -> None:
        """[acceptance②] 환율 미지정 시 0원이 아니라 미측정 — 하드코딩 환율 금지."""
        pid = uuid.uuid4()
        events = _reviewed_cu("cu-a", 60_000, problem_id=pid)
        report = aggregate(
            events,
            genlog_rows=[
                {"problem_id": str(pid), "cost_usd": 0.5, "input_tokens": 100, "output_tokens": 20}
            ],
        )
        record = build_record_from_report(
            report,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=None,
        )
        cost = record.kpis["unit_cost_krw"]
        assert cost.measured is False
        assert cost.value is None
        assert "환율" in cost.reason

    def test_failure_distribution_measured_when_rejections_exist(self) -> None:
        events = _reviewed_cu(
            "cu-a", 60_000, verdict="rejected", failure_code=GenerationFailureCode.F1
        )
        report = aggregate(events)
        record = build_record_from_report(
            report,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=None,
        )
        dist = record.kpis["failure_type_distribution"]
        assert dist.measured is True
        assert dist.value["F1"] == 1  # type: ignore[index]


class TestBuildRecordDbFailure:
    def test_report_none_marks_four_dynamic_kpis_unmeasured_with_reason(self) -> None:
        """[침묵 실패 금지] DB 실패는 예외 타입명이 사유에 실려야 한다."""
        record = build_record_from_report(
            None,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=1400,
            db_failure_reason="DB 연결/조회 실패 — OperationalError",
        )
        for name in (
            "hit_seconds",
            "throughput_cu_per_hour",
            "unit_cost_krw",
            "failure_type_distribution",
        ):
            assert record.kpis[name].measured is False, name
            assert "OperationalError" in (record.kpis[name].reason or ""), name
        # 구조적 미측정 2종도 여전히 존재(별개 사유)
        assert record.kpis["auto_gate_pass_rate"].measured is False


class TestCollectDbConnectionFailure:
    """`collect()` — 연결 자체가 실패하면 예외를 삼키지 않고 record로 안전 강등."""

    async def test_unreachable_database_url_yields_unmeasured_record_not_crash(self) -> None:
        record = await collect(
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=1400,
            database_url="postgresql+asyncpg://nope:nope@127.0.0.1:1/nonexistent",
        )
        assert record.kpis["hit_seconds"].measured is False
        assert record.kpis["hit_seconds"].reason  # 예외 타입명을 담은 사유 존재
        assert set(record.kpis) == set(KPI_NAMES)


class TestLoadAppendRecordLedger:
    def test_missing_file_loads_as_empty_list(self, tmp_path: Path) -> None:
        assert load_ledger(tmp_path / "weekly.json") == []

    def test_append_preserves_existing_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "weekly.json"
        first = build_record_from_report(
            _empty_report(),
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=None,
        )
        append_record(path, first)
        second_week_start = datetime(2026, 9, 8, tzinfo=UTC)
        second_week_end = datetime(2026, 9, 15, tzinfo=UTC)
        second = build_record_from_report(
            _empty_report(),
            week_start=second_week_start,
            week_end=second_week_end,
            generated_at=datetime(2026, 9, 15, 1, 0, tzinfo=UTC),
            krw_per_usd=None,
        )
        ledger = append_record(path, second)

        assert len(ledger) == 2
        assert ledger[0]["week_start"] == first.week_start
        assert ledger[1]["week_start"] == second.week_start
        # 디스크에 실제로 반영됐는지(메모리 반환값뿐 아니라) 재확인
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert len(reloaded) == 2

    def test_malformed_existing_file_raises_not_silently_overwritten(self, tmp_path: Path) -> None:
        """기존 원장이 배열이 아니면(손상) 조용히 덮어쓰지 않고 예외를 낸다."""
        path = tmp_path / "weekly.json"
        path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON 배열"):
            load_ledger(path)
