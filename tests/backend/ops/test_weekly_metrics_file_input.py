"""주간 KPI 파일 입력 모드(EOS-198 ① · 공백 G-A)와 cu_slug 조인(EOS-198 ② · 공백 G-B).

정본: `ops/weekly_metrics_report.py`(`report_from_files`·`collect_from_files`·
`_genlog_row_for_aggregate`). hermetic — DB에 연결하지 않는다. DB 경로(`_fetch_report`)는
**WHERE를 이미 적용한 행을 돌려주는 가짜 세션**으로 돌린다: 실 PG 쿼리 자체는
`test_weekly_metrics_report_integration.py`가 CI 실 PG 잡에서 본다.

검증 축:
  ① 같은 입력 → DB 경로와 파일 경로가 **같은 HitCuReport·같은 레코드**(파일 쪽엔 창 밖·시각
     없음 행까지 섞어, 창 판정이 DB WHERE와 같은 규칙인지도 함께 본다)
  ② 배치 저작 행(problem_id=None)의 비용이 cu_slug로 CU에 조인된다 — cu_slug를 지우는
     뮤테이션이 RED가 된다(대조군: cu_slug 없는 행은 미측정)
  ③ 입력 0건·필드 결손·파싱 실패·파일 없음·비용 입력 미지정 → measured:false(사유 동반)
  ④ CLI — 파일 모드는 DB를 부르지 않고, 인자 오류는 exit 2
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.db.models.provenance import GenerationLog as OrmGenerationLog
from whymath_backend.db.models.review_timer_event import ReviewTimerEvent as OrmReviewTimerEvent
from whymath_backend.harness.review_timer import finish_review, start_review
from whymath_backend.ops import weekly_metrics_report as wmr
from whymath_backend.schema.provenance import GenerationLog
from whymath_backend.schema.review_timer import ReviewTimerEvent

_WEEK_START = datetime(2026, 10, 20, tzinfo=UTC)
_WEEK_END = datetime(2026, 10, 27, tzinfo=UTC)
_INSIDE = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)
_OUTSIDE = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)  # 창 밖 — 섞이면 값이 바뀐다
_GENERATED_AT = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
_KRW = 1540.0


# ──────────────────────────────────────────────────────────────────────
# 픽스처 빌더
# ──────────────────────────────────────────────────────────────────────
def _review_pair(
    slug: str, elapsed_ms: int, recorded_at: datetime | None
) -> list[ReviewTimerEvent]:
    """시작·종료 이벤트 1쌍. recorded_at(수신 시각)이 창 판정 축이다(DB 쿼리와 같다)."""
    started = start_review(cu_slug=slug, reviewer_id="kiki", occurred_at=_INSIDE)
    finished = finish_review(
        review_session_id=started.review_session_id,
        cu_slug=slug,
        reviewer_id="kiki",
        verdict="approved",  # type: ignore[arg-type]
        elapsed_ms=elapsed_ms,
        occurred_at=_INSIDE + timedelta(milliseconds=elapsed_ms),
    )
    return [
        started.model_copy(update={"recorded_at": recorded_at}),
        finished.model_copy(update={"recorded_at": recorded_at}),
    ]


def _batch_log(
    slug: str | None,
    cost_usd: float | None,
    generated_at: datetime | None,
    *,
    tokens: tuple[int | None, int | None] = (3000, 1500),
) -> GenerationLog:
    """배치 저작 행 — problem_id=None(문제 행이 아직 없다)이 실제 저작 CLI의 모양이다."""
    return GenerationLog(
        model_name="deepseek/deepseek-v4.1-flash",
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        cost_usd=cost_usd,
        success=True,
        generated_at=generated_at,
        cu_slug=slug,
    )


def _write_jsonl(path: Path, rows: Sequence[Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    return path


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    """`_fetch_report`가 부르는 두 SELECT에 **창 안 행만** 돌려준다(= DB WHERE 적용 결과).

    쿼리 순서는 `_fetch_report` 본문이 정한다(이벤트 → 생성 로그). 세 번째 호출이 오면 구현이
    바뀐 것이므로 크게 실패한다.
    """

    def __init__(self, events: list[ReviewTimerEvent], logs: list[GenerationLog]) -> None:
        self._queue: list[list[Any]] = [
            [OrmReviewTimerEvent.from_schema(e) for e in events],
            [OrmGenerationLog.from_schema(g) for g in logs],
        ]

    async def execute(self, _statement: Any) -> _FakeResult:
        if not self._queue:
            raise AssertionError("_fetch_report가 예상보다 많은 쿼리를 냈다")
        return _FakeResult(self._queue.pop(0))


async def _db_report(events: list[ReviewTimerEvent], logs: list[GenerationLog]) -> Any:
    return await wmr._fetch_report(
        _FakeSession(events, logs),  # type: ignore[arg-type]
        week_start=_WEEK_START,
        week_end=_WEEK_END,
    )


def _record(report: Any, *, reason: str | None = None) -> dict[str, Any]:
    return wmr.build_record_from_report(
        report,
        week_start=_WEEK_START,
        week_end=_WEEK_END,
        generated_at=_GENERATED_AT,
        krw_per_usd=_KRW,
        db_failure_reason=reason,
    ).to_json()


# ──────────────────────────────────────────────────────────────────────
# ① DB 경로 ≡ 파일 경로
# ──────────────────────────────────────────────────────────────────────
class TestDbAndFilePathsAgree:
    async def test_same_input_same_report_and_same_record(self, tmp_path: Path) -> None:
        in_events = [
            *_review_pair("wm-gen-calc1-aaa", 95_000, _INSIDE),
            *_review_pair("wm-gen-calc1-bbb", 130_000, _INSIDE),
            *_review_pair("wm-gen-calc1-ccc", 210_000, _INSIDE),
        ]
        in_logs = [
            _batch_log("wm-gen-calc1-aaa", 0.0012, _INSIDE),
            _batch_log("wm-gen-calc1-bbb", 0.0015, _INSIDE),
            _batch_log("wm-gen-calc1-ccc", 0.0021, _INSIDE),
            _batch_log("wm-gen-calc1-ccc", 0.0004, _INSIDE),  # 같은 CU 재시도 — 합산돼야 한다
        ]
        # 파일 쪽에만 섞는다 — DB는 WHERE로 이미 뺐다. 섞인 채로 같은 값이 나와야 창 판정이 같다.
        out_events = [
            *_review_pair("wm-gen-calc1-aaa", 31_000, _OUTSIDE),
            *_review_pair("wm-gen-calc1-zzz", 40_000, None),
        ]
        out_logs = [
            _batch_log("wm-gen-calc1-aaa", 9.0, _OUTSIDE),
            _batch_log("wm-gen-calc1-bbb", 9.0, None),
        ]
        ev = _write_jsonl(tmp_path / "events.jsonl", [*in_events, *out_events])
        gl_a = _write_jsonl(tmp_path / "local" / "cu.genlog.jsonl", in_logs[:2] + out_logs[:1])
        gl_b = _write_jsonl(tmp_path / "or" / "cu.genlog.jsonl", in_logs[2:] + out_logs[1:])

        db_report = await _db_report(in_events, in_logs)
        file_report, summary, failure = wmr.report_from_files(
            events_paths=[ev],
            genlog_paths=[gl_a, gl_b],
            week_start=_WEEK_START,
            week_end=_WEEK_END,
        )

        assert failure is None
        assert summary is not None
        assert (summary.event_rows, summary.event_rows_in_window) == (10, 6)
        assert summary.event_rows_no_time == 2
        assert (summary.genlog_rows, summary.genlog_rows_in_window) == (6, 4)
        assert summary.genlog_rows_no_time == 1
        assert file_report == db_report
        assert _record(file_report) == _record(db_report)
        rec = _record(file_report)
        assert rec["kpis"]["hit_seconds"] == {
            "measured": True,
            "value": 130.0,
            "unit": "seconds_median",
            "reason": None,
        }
        assert rec["kpis"]["unit_cost_krw"]["measured"] is True
        assert rec["kpis"]["unit_cost_krw"]["value"] == pytest.approx(
            (0.0012 + 0.0015 + 0.0021 + 0.0004) * _KRW / 3
        )

    async def test_collect_from_files_record_shape_equals_db_record_shape(
        self, tmp_path: Path
    ) -> None:
        """원장 행 형태는 경로와 무관하다 — 키 집합·KPI 키 집합이 같다."""
        events = _review_pair("wm-gen-calc1-aaa", 95_000, _INSIDE)
        logs = [_batch_log("wm-gen-calc1-aaa", 0.001, _INSIDE)]
        record, _ = wmr.collect_from_files(
            events_paths=[_write_jsonl(tmp_path / "e.jsonl", events)],
            genlog_paths=[_write_jsonl(tmp_path / "g.jsonl", logs)],
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=_KRW,
        )
        db_rec = _record(await _db_report(events, logs))
        file_rec = record.to_json()
        assert set(file_rec) == set(db_rec)
        assert set(file_rec["kpis"]) == set(db_rec["kpis"]) == set(wmr.KPI_NAMES)
        assert file_rec["kpis"] == db_rec["kpis"]


# ──────────────────────────────────────────────────────────────────────
# ② cu_slug 조인 (공백 G-B 회귀)
# ──────────────────────────────────────────────────────────────────────
class TestCuSlugJoin:
    async def test_batch_row_cost_joins_through_cu_slug_on_db_path(self) -> None:
        """problem_id=None인 배치 행 — cu_slug가 실려야만 비용이 CU에 붙는다.

        뮤테이션 대상: `_genlog_row_for_aggregate`의 `"cu_slug": row.cu_slug` 줄. 지우면 이
        테스트가 measured False로 RED가 된다(종전 DB 경로의 결함 그대로).
        """
        events = _review_pair("wm-gen-calc1-aaa", 95_000, _INSIDE)
        logs = [_batch_log("wm-gen-calc1-aaa", 0.002, _INSIDE)]
        report = await _db_report(events, logs)
        assert report.cost_rows_matched == 1
        assert report.cu_with_cost == 1
        kpi = _record(report)["kpis"]["unit_cost_krw"]
        assert kpi["measured"] is True
        assert kpi["value"] == pytest.approx(0.002 * _KRW)

    def test_mapping_carries_cu_slug_and_keeps_none_as_none(self) -> None:
        row = wmr._genlog_row_for_aggregate(_batch_log("wm-x", None, _INSIDE, tokens=(None, 7)))
        assert row == {
            "problem_id": None,
            "cu_slug": "wm-x",
            "cost_usd": None,  # 0.0으로 접지 않는다(미계측 ≠ $0)
            "input_tokens": None,
            "output_tokens": 7,
        }

    async def test_control_row_without_slug_or_problem_id_stays_unmeasured(self) -> None:
        """대조군 — 열쇠가 둘 다 없으면 조인되지 않고 미측정이다(0원 산입 금지)."""
        events = _review_pair("wm-gen-calc1-aaa", 95_000, _INSIDE)
        logs = [_batch_log(None, 0.002, _INSIDE)]
        report = await _db_report(events, logs)
        assert report.cost_rows_unmatched == 1
        kpi = _record(report)["kpis"]["unit_cost_krw"]
        assert kpi["measured"] is False
        assert kpi["value"] is None


# ──────────────────────────────────────────────────────────────────────
# ③ 미측정은 정직하게
# ──────────────────────────────────────────────────────────────────────
class TestFileInputHonestUnmeasured:
    def _run(self, **kwargs: Any) -> tuple[dict[str, Any], Any]:
        record, summary = wmr.collect_from_files(
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=_KRW,
            **kwargs,
        )
        return record.to_json(), summary

    def test_zero_input_rows_is_unmeasured_not_zero(self, tmp_path: Path) -> None:
        ev = tmp_path / "e.jsonl"
        ev.write_text("", encoding="utf-8")
        gl = tmp_path / "g.jsonl"
        gl.write_text("", encoding="utf-8")
        rec, summary = self._run(events_paths=[ev], genlog_paths=[gl])
        assert summary.event_rows == 0
        for name in ("hit_seconds", "throughput_cu_per_hour", "unit_cost_krw"):
            assert rec["kpis"][name]["measured"] is False
            assert rec["kpis"][name]["value"] is None
            assert rec["kpis"][name]["reason"]

    def test_all_rows_outside_window_is_unmeasured(self, tmp_path: Path) -> None:
        """회차가 창 밖이면 0건이다 — 창을 잘못 잡은 것이 '측정됨'으로 나오면 안 된다."""
        ev = _write_jsonl(tmp_path / "e.jsonl", _review_pair("wm-a", 95_000, _OUTSIDE))
        gl = _write_jsonl(tmp_path / "g.jsonl", [_batch_log("wm-a", 0.002, _OUTSIDE)])
        rec, summary = self._run(events_paths=[ev], genlog_paths=[gl])
        assert (summary.event_rows, summary.event_rows_in_window) == (2, 0)
        assert rec["kpis"]["hit_seconds"]["measured"] is False
        assert rec["kpis"]["unit_cost_krw"]["measured"] is False

    def test_cost_null_rows_leave_unit_cost_unmeasured(self, tmp_path: Path) -> None:
        """필드 결손 — 비용 미기록 행은 부분합이라 단위비용 표본이 아니다."""
        ev = _write_jsonl(tmp_path / "e.jsonl", _review_pair("wm-a", 95_000, _INSIDE))
        gl = _write_jsonl(tmp_path / "g.jsonl", [_batch_log("wm-a", None, _INSIDE)])
        rec, _ = self._run(events_paths=[ev], genlog_paths=[gl])
        assert rec["kpis"]["hit_seconds"]["measured"] is True  # 대조 — HIT는 그대로 잰다
        assert rec["kpis"]["unit_cost_krw"]["measured"] is False

    def test_missing_slug_field_leaves_unit_cost_unmeasured(self, tmp_path: Path) -> None:
        ev = _write_jsonl(tmp_path / "e.jsonl", _review_pair("wm-a", 95_000, _INSIDE))
        gl = _write_jsonl(tmp_path / "g.jsonl", [_batch_log(None, 0.002, _INSIDE)])
        rec, _ = self._run(events_paths=[ev], genlog_paths=[gl])
        assert rec["kpis"]["unit_cost_krw"]["measured"] is False

    def test_no_generation_log_input_leaves_unit_cost_unmeasured(self, tmp_path: Path) -> None:
        ev = _write_jsonl(tmp_path / "e.jsonl", _review_pair("wm-a", 95_000, _INSIDE))
        rec, summary = self._run(events_paths=[ev], genlog_paths=None)
        assert summary.genlog_rows is None
        assert rec["kpis"]["hit_seconds"]["measured"] is True
        assert rec["kpis"]["unit_cost_krw"]["measured"] is False

    def test_parse_error_marks_dynamic_kpis_unmeasured(self, tmp_path: Path) -> None:
        """파싱 실패 1행 — 부분 입력으로 판정하지 않는다(나머지가 멀쩡해도)."""
        ev = _write_jsonl(tmp_path / "e.jsonl", _review_pair("wm-a", 95_000, _INSIDE))
        with ev.open("a", encoding="utf-8") as fh:
            fh.write("{깨진 줄\n")
        gl = _write_jsonl(tmp_path / "g.jsonl", [_batch_log("wm-a", 0.002, _INSIDE)])
        rec, summary = self._run(events_paths=[ev], genlog_paths=[gl])
        assert len(summary.parse_errors) == 1
        for name in (
            "hit_seconds",
            "throughput_cu_per_hour",
            "unit_cost_krw",
            "failure_type_distribution",
        ):
            assert rec["kpis"][name]["measured"] is False
            assert "파싱 실패" in rec["kpis"][name]["reason"]

    def test_missing_file_is_unmeasured_with_exception_type(self, tmp_path: Path) -> None:
        rec, summary = self._run(events_paths=[tmp_path / "없음.jsonl"], genlog_paths=None)
        assert summary is None
        assert rec["kpis"]["hit_seconds"]["measured"] is False
        assert "FileNotFoundError" in rec["kpis"]["hit_seconds"]["reason"]


# ──────────────────────────────────────────────────────────────────────
# ④ CLI
# ──────────────────────────────────────────────────────────────────────
class TestFileModeCli:
    def _files(self, tmp_path: Path) -> tuple[Path, Path]:
        ev = _write_jsonl(tmp_path / "e.jsonl", _review_pair("wm-a", 95_000, _INSIDE))
        gl = _write_jsonl(tmp_path / "g.jsonl", [_batch_log("wm-a", 0.002, _INSIDE)])
        return ev, gl

    def test_file_mode_never_touches_db_and_appends_measured_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def _no_db(**_kwargs: Any) -> Any:
            raise AssertionError("파일 입력 모드가 DB 경로(collect)를 불렀다")

        monkeypatch.setattr(wmr, "collect", _no_db)
        ev, gl = self._files(tmp_path)
        ledger = tmp_path / "metrics" / "weekly.json"
        code = wmr.main(
            [
                "--metrics-path",
                str(ledger),
                "--events-jsonl",
                str(ev),
                "--generation-log-jsonl",
                str(gl),
                "--week-start",
                _WEEK_START.isoformat(),
                "--week-end",
                _WEEK_END.isoformat(),
                "--krw-per-usd",
                str(_KRW),
            ]
        )
        assert code == 0
        rows = json.loads(ledger.read_text(encoding="utf-8"))
        assert len(rows) == 1
        assert rows[0]["week_start"] == _WEEK_START.isoformat()
        assert rows[0]["kpis"]["hit_seconds"]["measured"] is True
        assert rows[0]["kpis"]["unit_cost_krw"]["measured"] is True
        err = capsys.readouterr().err
        assert "[파일 입력]" in err and "창 안 2행" in err

    def test_naive_window_is_read_as_utc(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ev, gl = self._files(tmp_path)
        code = wmr.main(
            [
                "--dry-run",
                "--events-jsonl",
                str(ev),
                "--generation-log-jsonl",
                str(gl),
                "--week-start",
                "2026-10-20T00:00:00",
                "--week-end",
                "2026-10-27T00:00:00",
            ]
        )
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["week_start"] == _WEEK_START.isoformat()
        assert out["kpis"]["hit_seconds"]["measured"] is True

    @pytest.mark.parametrize(
        "extra",
        [
            ["--generation-log-jsonl", "g.jsonl"],  # 비용 입력만 — 파일 모드 아님
            ["--events-jsonl", "e.jsonl", "--week-start", "2026-10-20T00:00:00+00:00"],
            [
                "--events-jsonl",
                "e.jsonl",
                "--week-start",
                "2026-10-27T00:00:00+00:00",
                "--week-end",
                "2026-10-20T00:00:00+00:00",
            ],
            ["--events-jsonl", "e.jsonl", "--week-start", "어제", "--week-end", "오늘"],
        ],
    )
    def test_argument_errors_exit_2(self, extra: list[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            wmr.main(["--dry-run", *extra])
        assert excinfo.value.code == 2


# ──────────────────────────────────────────────────────────────────────
# EOS-198 P2-1 — 파일 모드 PK 중복 제거(같은 파일을 두 번 줘도 값 불변)
# ──────────────────────────────────────────────────────────────────────
class TestDuplicateInputIsIdempotent:
    def _two_cu_files(self, tmp_path: Path) -> tuple[Path, Path]:
        ev = _write_jsonl(
            tmp_path / "e.jsonl",
            [*_review_pair("wm-a", 95_000, _INSIDE), *_review_pair("wm-b", 125_000, _INSIDE)],
        )
        gl = _write_jsonl(
            tmp_path / "g.jsonl",
            [_batch_log("wm-a", 0.0010, _INSIDE), _batch_log("wm-b", 0.0020, _INSIDE)],
        )
        return ev, gl

    def _kpis(self, ev: list[Path], gl: list[Path]) -> tuple[dict[str, Any], Any]:
        record, summary = wmr.collect_from_files(
            events_paths=ev,
            genlog_paths=gl,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=_KRW,
        )
        return record.to_json()["kpis"], summary

    def test_same_genlog_file_twice_keeps_unit_cost(self, tmp_path: Path) -> None:
        ev, gl = self._two_cu_files(tmp_path)
        once, _ = self._kpis([ev], [gl])
        twice, summary = self._kpis([ev], [gl, gl])
        assert once["unit_cost_krw"]["measured"] is True
        assert twice["unit_cost_krw"] == once["unit_cost_krw"]  # 두 배가 되면 안 된다
        assert once["unit_cost_krw"]["value"] == pytest.approx((0.0010 + 0.0020) * _KRW / 2)
        assert summary.genlog_duplicates == 2

    def test_same_events_file_twice_keeps_hit(self, tmp_path: Path) -> None:
        ev, gl = self._two_cu_files(tmp_path)
        once, _ = self._kpis([ev], [gl])
        twice, summary = self._kpis([ev, ev], [gl])
        assert twice == once
        assert summary.event_duplicates == 4

    def test_genlog_row_without_log_id_fails_closed(self, tmp_path: Path) -> None:
        """PK 없는 행은 읽을 때마다 새 PK를 받아 중복 판정이 불가능하다 — 입력 실패로 친다."""
        ev, _ = self._two_cu_files(tmp_path)
        raw = json.loads(_batch_log("wm-a", 0.0010, _INSIDE).model_dump_json())
        del raw["log_id"]
        gl = tmp_path / "no_pk.jsonl"
        gl.write_text(json.dumps(raw) + "\n", encoding="utf-8")
        kpis, summary = self._kpis([ev], [gl])
        assert any("MissingPrimaryKey(log_id)" in e for e in summary.parse_errors)
        assert kpis["unit_cost_krw"]["measured"] is False
        assert kpis["hit_seconds"]["measured"] is False  # 부분 입력으로 판정하지 않는다

    def test_event_row_without_event_id_fails_closed(self, tmp_path: Path) -> None:
        _, gl = self._two_cu_files(tmp_path)
        rows = [json.loads(e.model_dump_json()) for e in _review_pair("wm-a", 95_000, _INSIDE)]
        del rows[1]["event_id"]
        ev = tmp_path / "no_pk_events.jsonl"
        ev.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        kpis, summary = self._kpis([ev], [gl])
        assert any("MissingPrimaryKey(event_id)" in e for e in summary.parse_errors)
        assert kpis["hit_seconds"]["measured"] is False

    def test_same_log_id_with_different_content_is_a_conflict(self, tmp_path: Path) -> None:
        ev, gl = self._two_cu_files(tmp_path)
        first = _batch_log("wm-a", 0.0010, _INSIDE)
        tampered = first.model_copy(update={"cost_usd": 0.9})
        gl2 = _write_jsonl(tmp_path / "g2.jsonl", [tampered])
        kpis, summary = self._kpis([ev], [_write_jsonl(tmp_path / "g1.jsonl", [first]), gl2])
        assert any("충돌" in e for e in summary.parse_errors)
        assert kpis["unit_cost_krw"]["measured"] is False


# ──────────────────────────────────────────────────────────────────────
# EOS-198 P3-1 — 단위비용 분자·분모는 같은 CU 집합(완전 계측 CU)
# ──────────────────────────────────────────────────────────────────────
class TestUnitCostUsesOneCuSet:
    """CU a = 완전 계측($0.0015) · CU b = 비용 행 $0.0015 + 비용 null 행(부분 기록).

    올바른 값 = a만의 평균 = 0.0015 × 1540 = 2.31원. 종전엔 분자에 b의 부분합이 들어가고
    분모엔 빠져 4.62원(두 배)이 measured:true로 나갔다.
    """

    def _inputs(self) -> tuple[list[ReviewTimerEvent], list[GenerationLog]]:
        events = [*_review_pair("wm-a", 95_000, _INSIDE), *_review_pair("wm-b", 125_000, _INSIDE)]
        logs = [
            _batch_log("wm-a", 0.0015, _INSIDE),
            _batch_log("wm-b", 0.0015, _INSIDE),
            _batch_log("wm-b", None, _INSIDE),  # 같은 CU의 비용 미기록 호출 → b는 부분 기록
        ]
        return events, logs

    def _assert_complete_set_only(self, kpi: dict[str, Any]) -> None:
        assert kpi["measured"] is True
        assert kpi["value"] == pytest.approx(0.0015 * _KRW)  # 2.31 — 4.62가 아니다
        assert kpi["reason"] is not None and "부분 표본" in kpi["reason"]
        assert "1건" in kpi["reason"]  # 제외된 CU 수가 원장에서 보인다

    async def test_db_path(self) -> None:
        events, logs = self._inputs()
        report = await _db_report(events, logs)
        assert (report.cu_with_cost, report.cu_cost_incomplete) == (1, 1)
        self._assert_complete_set_only(_record(report)["kpis"]["unit_cost_krw"])

    def test_file_path(self, tmp_path: Path) -> None:
        events, logs = self._inputs()
        record, _ = wmr.collect_from_files(
            events_paths=[_write_jsonl(tmp_path / "e.jsonl", events)],
            genlog_paths=[_write_jsonl(tmp_path / "g.jsonl", logs)],
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_GENERATED_AT,
            krw_per_usd=_KRW,
        )
        self._assert_complete_set_only(record.to_json()["kpis"]["unit_cost_krw"])

    async def test_no_incomplete_cu_has_no_reason(self) -> None:
        """대조군 — 부분 기록 CU가 없으면 사유 없이 전체 평균이다."""
        events = _review_pair("wm-a", 95_000, _INSIDE)
        report = await _db_report(events, [_batch_log("wm-a", 0.0015, _INSIDE)])
        kpi = _record(report)["kpis"]["unit_cost_krw"]
        assert kpi == {
            "measured": True,
            "value": pytest.approx(0.0015 * _KRW),
            "unit": "krw_per_cu",
            "reason": None,
        }


# ──────────────────────────────────────────────────────────────────────
# EOS-198 P3-2 — 창 경계: 시작은 포함, 끝은 미포함(DB WHERE `>= start AND < end`)
# ──────────────────────────────────────────────────────────────────────
class TestWindowBoundaries:
    def _report(self, tmp_path: Path, moment: datetime) -> Any:
        report, summary, failure = wmr.report_from_files(
            events_paths=[_write_jsonl(tmp_path / "e.jsonl", _review_pair("wm-a", 95_000, moment))],
            genlog_paths=[_write_jsonl(tmp_path / "g.jsonl", [_batch_log("wm-a", 0.001, moment)])],
            week_start=_WEEK_START,
            week_end=_WEEK_END,
        )
        assert failure is None
        return report, summary

    def test_row_exactly_at_week_end_is_outside(self, tmp_path: Path) -> None:
        report, summary = self._report(tmp_path, _WEEK_END)
        assert summary.event_rows_in_window == 0
        assert summary.genlog_rows_in_window == 0
        assert report.cu_measured == 0

    def test_row_exactly_at_week_start_is_inside(self, tmp_path: Path) -> None:
        report, summary = self._report(tmp_path, _WEEK_START)
        assert summary.event_rows_in_window == 2
        assert summary.genlog_rows_in_window == 1
        assert report.cu_measured == 1

    def test_one_microsecond_before_week_end_is_inside(self, tmp_path: Path) -> None:
        report, _ = self._report(tmp_path, _WEEK_END - timedelta(microseconds=1))
        assert report.cu_measured == 1
