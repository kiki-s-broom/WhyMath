"""[EOS-220] 주간 KPI — 재작업률(슬롯 기록 좌석) + 두 KPI의 근거(detail) + 위반 주입 변별력.

검증 계약
--------
① 1회차(EOS-197 A6) 소급: 자동검증 1차 통과율 13/111(Wilson 단측 하한 ≈0.0758 — EOS-207 문서와
   같다) measured. 재작업률은 슬롯 기록(`cu.slots.jsonl`)이 없어 **미측정 + 사유**다 — 생성 로그만으로
   세면 값이 배치 안 순서에 좌우되므로 세지 않는다(0으로도 떨어지지 않는다).
② 정의: 슬롯 안 시도 번호로 센다 — CU가 k번째 시도에서 나오면 재생성 k−1.
③ 변별력: 위반을 주입하면 값이 바뀌거나 미측정(사유 포함)으로 떨어진다. 주입이 실제로 적용됐는지
   (`mutated != original`)를 매번 단언한다.
④ 원장 모양: `detail`은 측정된 두 KPI에만 붙고 나머지 4종은 종전 4키 그대로다.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.ops import weekly_metrics_report as wmr

_RUNS = Path(__file__).resolve().parents[3] / "data" / "runs"
_SEATS = ("eos197-a6-local", "eos197-a6-openrouter")
_WINDOW = (
    datetime(2026, 10, 27, 14, 6, 14, 101338, tzinfo=UTC),
    datetime(2026, 10, 28, 7, 52, 53, 299873, tzinfo=UTC),
)  # 원장 2026-10-28T07:57:24Z 레코드의 창(EOS-197 ⑦ (d))
_SYN = (datetime(2026, 10, 27, tzinfo=UTC), datetime(2026, 10, 28, tzinfo=UTC))


def _rework(dirs: list[Path], window: tuple[datetime, datetime] = _SYN) -> wmr.KpiValue:
    return wmr.rework_kpi_from_run_dirs(dirs, week_start=window[0], week_end=window[1])


def _auto_gate(dirs: list[Path]) -> wmr.KpiValue:
    return wmr.auto_gate_kpi_from_run_dirs(dirs, week_start=_WINDOW[0], week_end=_WINDOW[1])


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def _mutate(path: Path, fn: Any) -> None:
    """JSONL 행 변환 주입 — 주입이 실제로 적용됐는지(내용이 바뀌었는지) 단언한다."""
    original = path.read_bytes()
    _write_rows(path, fn(_rows(path)))
    assert path.read_bytes() != original, f"주입이 적용되지 않았다: {path.name}"


def _seat(tmp_path: Path, name: str, slots: dict[str, str]) -> Path:
    """`slots` = 슬롯 id → 시도열. 문자 하나 = 시도 하나(O=CU · x=CU 아님). 시각은 시도마다 1분."""
    seat = tmp_path / name
    seat.mkdir()
    cu, slot_rows, minute = [], [], 0
    for slot_id, sequence in slots.items():
        for attempt, ch in enumerate(sequence, start=1):
            at = f"2026-10-27T15:{minute:02d}:00+00:00"
            minute += 1
            slug = f"{name}-{slot_id}-{attempt}" if ch == "O" else None
            slot_rows.append(
                {
                    "slot_id": slot_id,
                    "attempt": attempt,
                    "outcome": "cu" if ch == "O" else "not_cu",
                    "cu_slug": slug,
                    "recorded_at": at,
                }
            )
            if slug is not None:
                cu.append({"slug": slug})
    _write_rows(seat / "cu.jsonl", cu)
    _write_rows(seat / "cu.genlog.jsonl", [])
    _write_rows(seat / wmr.SLOT_LOG_FILE, slot_rows)
    return seat


# ──────────────────────────────────────────────────────────────────────
# ① 1회차 소급
# ──────────────────────────────────────────────────────────────────────
class TestRound1:
    def test_rework_is_unmeasured_without_slot_seat(self) -> None:
        dirs = [_RUNS / s for s in _SEATS]
        assert not any((d / wmr.SLOT_LOG_FILE).exists() for d in dirs)  # 전제 확인
        kpi = _rework(dirs, window=_WINDOW)
        assert kpi.measured is False
        assert kpi.value is None
        assert kpi.reason is not None and wmr.SLOT_LOG_FILE in kpi.reason
        assert "배치" in kpi.reason

    def test_auto_gate_detail_matches_eos207(self) -> None:
        kpi = _auto_gate([_RUNS / s for s in _SEATS])
        assert kpi.measured is True
        assert kpi.detail is not None
        assert (kpi.detail["numerator"], kpi.detail["denominator"]) == (13, 111)
        # EOS-207 문서(docs/reviews/eos207_g3_measures_2026-10-29.md)의 Wilson 단측 하한 0.0758
        assert kpi.detail["wilson_lower_95"] == pytest.approx(0.0758, abs=5e-5)
        assert kpi.detail["run_dirs"] == [str(_RUNS / s) for s in _SEATS]


# ──────────────────────────────────────────────────────────────────────
# ② 정의 — 합성 슬롯 기록
# ──────────────────────────────────────────────────────────────────────
class TestDefinition:
    def test_regenerations_are_attempt_minus_one(self, tmp_path: Path) -> None:
        # 같은 좌석 안 슬롯 4개: 재생성 0 · 1 · 2, 그리고 CU 미산출 1
        seat = _seat(tmp_path, "r", {"s1": "O", "s2": "xO", "s3": "xxO", "s4": "xx"})
        kpi = _rework([seat])
        assert kpi.measured is True
        assert kpi.value == pytest.approx(2 / 3)
        assert kpi.detail is not None
        assert kpi.detail["repeat_numerator"] == 1
        assert kpi.detail["open_slots"] == 1
        assert kpi.detail["regeneration_distribution"] == {"0": 1, "1": 1, "2": 1}

    def test_slots_in_same_seat_are_independent(self, tmp_path: Path) -> None:
        # 같은 좌석의 다른 슬롯 실패는 이 CU의 재생성이 아니다(시각상 앞이어도).
        seat = _seat(tmp_path, "r", {"a": "xxx", "b": "O"})
        kpi = _rework([seat])
        assert kpi.value == 0.0
        assert kpi.detail is not None and kpi.detail["open_slots"] == 1

    def test_cu_outside_window_is_not_counted(self, tmp_path: Path) -> None:
        seat = _seat(tmp_path, "r", {"s1": "xO", "s2": "O"})
        late = (datetime(2026, 10, 27, 15, 2, tzinfo=UTC), _SYN[1])  # s2의 CU(15:02)만 창 안
        kpi = _rework([seat], window=late)
        assert kpi.value == 0.0
        assert kpi.detail is not None and kpi.detail["outside_window_cu"] == 1

    def test_no_cu_is_unmeasured(self, tmp_path: Path) -> None:
        kpi = _rework([_seat(tmp_path, "r", {"s1": "xx"})])
        assert kpi.measured is False and kpi.value is None
        assert kpi.reason is not None and "분모 0" in kpi.reason


# ──────────────────────────────────────────────────────────────────────
# ③ 변별력 — 위반 주입
# ──────────────────────────────────────────────────────────────────────
class TestInjection:
    def test_adding_a_failed_attempt_changes_value(self, tmp_path: Path) -> None:
        seat = _seat(tmp_path, "r", {"s1": "O", "s2": "O"})
        base = _rework([seat])

        def prepend_failure(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            bumped = [
                {**r, "attempt": r["attempt"] + 1} if r["slot_id"] == "s1" else r for r in rows
            ]
            first = {**rows[0], "attempt": 1, "outcome": "not_cu", "cu_slug": None}
            return [first, *bumped]

        _mutate(seat / wmr.SLOT_LOG_FILE, prepend_failure)
        after = _rework([seat])
        assert (base.value, after.value) == (0.0, 0.5)

    @pytest.mark.parametrize(
        ("name", "mutation", "needle"),
        [
            ("gap", lambda rs: [r for r in rs if r["attempt"] != 1], "1..k"),
            (
                "cu_not_last",
                lambda rs: rs + [{**rs[-1], "attempt": 3, "outcome": "not_cu", "cu_slug": None}],
                "CU 뒤에",
            ),
            ("bad_outcome", lambda rs: [{**rs[0], "outcome": "pass"}] + rs[1:], "outcome"),
            ("no_time", lambda rs: [{**rs[0], "recorded_at": None}] + rs[1:], "recorded_at"),
            ("bool_attempt", lambda rs: [{**rs[0], "attempt": True}] + rs[1:], "attempt"),
            ("slug_mismatch", lambda rs: rs[:-1] + [{**rs[-1], "cu_slug": "other"}], "회계 불일치"),
        ],
    )
    def test_broken_slot_log_is_unmeasured(
        self, tmp_path: Path, name: str, mutation: Any, needle: str
    ) -> None:
        seat = _seat(tmp_path, "r", {"s1": "xO"})
        _mutate(seat / wmr.SLOT_LOG_FILE, mutation)
        kpi = _rework([seat])
        assert kpi.measured is False, name
        assert kpi.value is None
        assert kpi.reason is not None and needle in kpi.reason, kpi.reason

    def test_one_seat_without_slot_log_fails_whole_measure(self, tmp_path: Path) -> None:
        good = _seat(tmp_path, "a", {"s1": "O"})
        bad = _seat(tmp_path, "b", {"s1": "O"})
        (bad / wmr.SLOT_LOG_FILE).unlink()
        assert not (bad / wmr.SLOT_LOG_FILE).exists()
        kpi = _rework([good, bad])
        assert kpi.measured is False  # 부분 입력으로 판정하지 않는다

    def test_corrupt_line_is_unmeasured(self, tmp_path: Path) -> None:
        seat = _seat(tmp_path, "r", {"s1": "O"})
        path = seat / wmr.SLOT_LOG_FILE
        original = path.read_bytes()
        path.write_bytes(original + b"{broken\n")
        assert path.read_bytes() != original
        kpi = _rework([seat])
        assert kpi.measured is False
        assert kpi.reason is not None and "JSON 파싱 실패" in kpi.reason

    def test_run_dir_load_error_propagates(self, tmp_path: Path) -> None:
        seat = _seat(tmp_path, "r", {"s1": "O"})
        (seat / "cu.genlog.jsonl").unlink()
        kpi = _rework([seat])
        assert kpi.measured is False
        assert kpi.reason is not None and "cu.genlog.jsonl 없음" in kpi.reason

    def test_dropping_a_cu_changes_auto_gate_value(self, tmp_path: Path) -> None:
        dirs = []
        for seat in _SEATS:
            shutil.copytree(_RUNS / seat, tmp_path / seat)
            dirs.append(tmp_path / seat)
        base = _auto_gate(dirs)
        slug = _rows(dirs[1] / "cu.jsonl")[0]["slug"]
        _mutate(dirs[1] / "cu.jsonl", lambda rs: [r for r in rs if r["slug"] != slug])
        _mutate(dirs[1] / "cu.genlog.jsonl", lambda rs: [r for r in rs if r.get("cu_slug") != slug])
        after = _auto_gate(dirs)
        assert after.measured is True
        assert after.detail is not None and base.detail is not None
        assert after.detail["denominator"] == base.detail["denominator"] - 1
        assert after.value != base.value


# ──────────────────────────────────────────────────────────────────────
# ④ 원장 레코드 모양
# ──────────────────────────────────────────────────────────────────────
class TestRecordShape:
    def test_detail_only_on_measured_run_dir_kpis(self) -> None:
        events = _RUNS / "eos197-a6-review" / "canary_review_events.jsonl"
        record, _ = wmr.collect_from_files(
            events_paths=[events],
            genlog_paths=[_RUNS / s / "cu.genlog.jsonl" for s in _SEATS],
            week_start=_WINDOW[0],
            week_end=_WINDOW[1],
            generated_at=_WINDOW[1],
            krw_per_usd=1540.0,
            authoring_run_dirs=[_RUNS / s for s in _SEATS],
        )
        kpis = record.to_json()["kpis"]
        measured = {k for k, v in kpis.items() if v["measured"]}
        assert measured == set(wmr.KPI_NAMES) - {"rework_rate"}
        assert {k for k, v in kpis.items() if "detail" in v} == {"auto_gate_pass_rate"}
        assert set(kpis["hit_seconds"]) == {"measured", "value", "unit", "reason"}
        assert wmr.SLOT_LOG_FILE in (kpis["rework_rate"]["reason"] or "")

    def test_without_run_dirs_rework_stays_structurally_unmeasured(self) -> None:
        record = wmr.build_record_from_report(
            None,
            week_start=_WINDOW[0],
            week_end=_WINDOW[1],
            generated_at=_WINDOW[1],
            krw_per_usd=None,
        )
        rework = record.kpis["rework_rate"]
        assert rework.measured is False and rework.value is None
        assert rework.reason == wmr.STRUCTURALLY_UNMEASURED["rework_rate"]
        assert "detail" not in rework.to_json()
