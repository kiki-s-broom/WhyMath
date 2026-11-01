"""[EOS-220] 주간 KPI — 재작업률 산출 + 두 KPI의 근거(detail) + 위반 주입 변별력.

검증 계약
--------
① 1회차(EOS-197 A6) 소급값: 자동검증 1차 통과율 13/111(Wilson 단측 하한 ≈0.0758 — EOS-207 문서와
   같다) · 재작업률 19/30 · 2회+ 재생성 10/30 · CU를 못 낸 시도 49건.
② 정의: 좌석×생성 주제 슬롯의 시간순 시도열에서 CU 앞의 CU 아닌 시도 = 재생성.
③ 변별력: 실데이터 사본에 위반을 주입하면 값이 바뀌거나 미측정(사유 포함)으로 떨어진다 — 0으로
   떨어지지 않는다. 주입이 실제로 적용됐는지(`mutated != original`)를 매번 단언한다.
④ 원장 모양: `detail`은 두 KPI에만 붙고 나머지 4종은 종전 4키 그대로다.
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
_FAR = (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC))


def _rework(dirs: list[Path], window: tuple[datetime, datetime] = _WINDOW) -> wmr.KpiValue:
    return wmr.rework_kpi_from_run_dirs(dirs, week_start=window[0], week_end=window[1])


def _auto_gate(dirs: list[Path]) -> wmr.KpiValue:
    return wmr.auto_gate_kpi_from_run_dirs(dirs, week_start=_WINDOW[0], week_end=_WINDOW[1])


def _copy_seats(tmp_path: Path) -> list[Path]:
    out = []
    for seat in _SEATS:
        dst = tmp_path / seat
        shutil.copytree(_RUNS / seat, dst)
        out.append(dst)
    return out


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def _mutate(path: Path, fn: Any) -> None:
    """JSONL 행 변환 주입 — 주입이 실제로 적용됐는지(내용이 바뀌었는지) 단언한다."""
    original = path.read_bytes()
    _write_rows(path, fn(_rows(path)))
    assert path.read_bytes() != original, f"주입이 적용되지 않았다: {path.name}"


# ──────────────────────────────────────────────────────────────────────
# ① 1회차 소급값
# ──────────────────────────────────────────────────────────────────────
class TestRound1Values:
    def test_rework_values(self) -> None:
        kpi = _rework([_RUNS / s for s in _SEATS])
        assert kpi.measured is True
        assert kpi.value == pytest.approx(19 / 30)
        assert kpi.detail is not None
        assert (kpi.detail["numerator"], kpi.detail["denominator"]) == (19, 30)
        assert (kpi.detail["repeat_numerator"], kpi.detail["abandoned_attempts"]) == (10, 49)
        assert kpi.detail["regenerations"] == 57
        assert kpi.detail["wilson_upper_95"] > 19 / 30  # 낮을수록 좋은 지표 → 상한

    def test_auto_gate_detail_matches_eos207(self) -> None:
        kpi = _auto_gate([_RUNS / s for s in _SEATS])
        assert kpi.measured is True
        assert kpi.detail is not None
        assert (kpi.detail["numerator"], kpi.detail["denominator"]) == (13, 111)
        # EOS-207 문서(docs/reviews/eos207_g3_measures_2026-10-29.md)의 Wilson 단측 하한 0.0758
        assert kpi.detail["wilson_lower_95"] == pytest.approx(0.0758, abs=5e-5)
        assert kpi.detail["run_dirs"] == [str(_RUNS / s) for s in _SEATS]

    def test_outside_window_is_unmeasured_not_zero(self) -> None:
        kpi = _rework([_RUNS / s for s in _SEATS], window=_FAR)
        assert kpi.measured is False
        assert kpi.value is None
        assert kpi.reason is not None and "분모 0" in kpi.reason


# ──────────────────────────────────────────────────────────────────────
# ② 정의 — 합성 시도열
# ──────────────────────────────────────────────────────────────────────
def _seat(tmp_path: Path, name: str, sequence: str, topic: str = "주제A") -> Path:
    """`sequence` 문자 하나 = 시도 하나(시간순). O=CU 저장 · x=생성 실패 · g=게이트 거부."""
    seat = tmp_path / name
    seat.mkdir()
    cu, review, genlog = [], [], []
    for i, ch in enumerate(sequence):
        at = f"2026-10-27T15:{i:02d}:00+00:00"
        snap = {"topic_hint": topic}
        if ch == "x":
            genlog.append(
                {
                    "log_id": f"{name}-{i}",
                    "success": False,
                    "cu_slug": None,
                    "generated_at": at,
                    "error_detail": "응답 JSON 파싱 실패",
                    "input_snapshot": snap,
                }
            )
            review.append({"slug": None, "status": "generation_failed", "recorded_at": at})
            continue
        slug = f"{name}-s{i}"
        genlog.append(
            {
                "log_id": f"{name}-{i}",
                "success": True,
                "cu_slug": slug,
                "generated_at": at,
                "input_snapshot": snap,
            }
        )
        if ch == "O":
            cu.append({"slug": slug, "verify": None})
        else:
            review.append({"slug": slug, "status": "rejected_gate", "recorded_at": at})
    _write_rows(seat / "cu.jsonl", cu)
    _write_rows(seat / "cu.review.jsonl", review)
    _write_rows(seat / "cu.genlog.jsonl", genlog)
    return seat


_SYN_WINDOW = (datetime(2026, 10, 27, tzinfo=UTC), datetime(2026, 10, 28, tzinfo=UTC))


class TestDefinition:
    def test_regenerations_attach_to_next_cu(self, tmp_path: Path) -> None:
        # CU1은 앞 시도 2건(재생성 2) · CU2는 바로(0) · 끝의 x 1건은 버려진 시도
        kpi = _rework([_seat(tmp_path, "r", "xgOOx")], window=_SYN_WINDOW)
        assert kpi.measured is True
        assert kpi.value == pytest.approx(1 / 2)
        assert kpi.detail is not None
        assert kpi.detail["repeat_numerator"] == 1
        assert kpi.detail["abandoned_attempts"] == 1
        assert kpi.detail["regeneration_distribution"] == {"0": 1, "2": 1}

    def test_slots_are_per_topic(self, tmp_path: Path) -> None:
        # 다른 주제의 실패는 이 주제 CU의 재생성이 아니다.
        a = _seat(tmp_path, "a", "O", topic="주제A")
        b = _seat(tmp_path, "b", "xx", topic="주제B")
        kpi = _rework([a, b], window=_SYN_WINDOW)
        assert kpi.value == 0.0
        assert kpi.detail is not None and kpi.detail["abandoned_attempts"] == 2

    def test_no_cu_is_unmeasured(self, tmp_path: Path) -> None:
        kpi = _rework([_seat(tmp_path, "r", "xxg")], window=_SYN_WINDOW)
        assert kpi.measured is False and kpi.value is None

    def test_unorderable_slug_mix_is_unmeasured(self, tmp_path: Path) -> None:
        seat = _seat(tmp_path, "r", "O")
        slug = _rows(seat / "cu.jsonl")[0]["slug"]
        # 같은 slug에 저장과 검수 대기가 섞이면 어느 시도가 CU인지 정할 수 없다.
        _mutate(seat / "cu.genlog.jsonl", lambda rs: rs + [{**rs[0], "log_id": "dup"}])
        _mutate(
            seat / "cu.review.jsonl",
            lambda rs: rs + [{"slug": slug, "status": "needs_review", "recorded_at": "x"}],
        )
        kpi = _rework([seat], window=_SYN_WINDOW)
        assert kpi.measured is False
        assert kpi.reason is not None and "결과 순서 판정 불가" in kpi.reason


# ──────────────────────────────────────────────────────────────────────
# ③ 변별력 — 실데이터 사본에 위반 주입
# ──────────────────────────────────────────────────────────────────────
class TestInjection:
    def test_dropping_failed_attempts_changes_rework_value(self, tmp_path: Path) -> None:
        dirs = _copy_seats(tmp_path)
        base = _rework(dirs)
        for seat in dirs:
            _mutate(seat / "cu.genlog.jsonl", lambda rs: [r for r in rs if r["success"]])
            _mutate(
                seat / "cu.review.jsonl",
                lambda rs: [r for r in rs if r["status"] != "generation_failed"],
            )
        after = _rework(dirs)
        assert after.measured is True
        assert after.value is not None and base.value is not None
        assert after.value < base.value

    def test_dropping_a_cu_changes_auto_gate_value(self, tmp_path: Path) -> None:
        dirs = _copy_seats(tmp_path)
        seat = dirs[1]
        base = _auto_gate(dirs)
        slug = _rows(seat / "cu.jsonl")[0]["slug"]
        _mutate(seat / "cu.jsonl", lambda rs: [r for r in rs if r["slug"] != slug])
        _mutate(seat / "cu.genlog.jsonl", lambda rs: [r for r in rs if r.get("cu_slug") != slug])
        after = _auto_gate(dirs)
        assert after.measured is True
        assert after.detail is not None and base.detail is not None
        assert after.detail["denominator"] == base.detail["denominator"] - 1
        assert after.value != base.value

    @pytest.mark.parametrize(
        ("name", "mutation", "needle"),
        [
            (
                "topic_missing",
                lambda rs: [{**rs[0], "input_snapshot": {}}] + rs[1:],
                "주제 없음",
            ),
            ("time_missing", lambda rs: [{**rs[0], "generated_at": None}] + rs[1:], "시각 없음"),
            (
                "accounting_break",
                lambda rs: [r for r in rs if r["success"]][:-1]
                + [r for r in rs if not r["success"]],
                "회계 불일치",
            ),
        ],
    )
    def test_broken_genlog_is_unmeasured_with_reason(
        self, tmp_path: Path, name: str, mutation: Any, needle: str
    ) -> None:
        dirs = _copy_seats(tmp_path)
        _mutate(dirs[1] / "cu.genlog.jsonl", mutation)
        kpi = _rework(dirs)
        assert kpi.measured is False, name
        assert kpi.value is None
        assert kpi.reason is not None and needle in kpi.reason

    def test_missing_genlog_file_is_unmeasured(self, tmp_path: Path) -> None:
        dirs = _copy_seats(tmp_path)
        (dirs[0] / "cu.genlog.jsonl").unlink()
        assert not (dirs[0] / "cu.genlog.jsonl").exists()
        for kpi in (_rework(dirs), _auto_gate(dirs)):
            assert kpi.measured is False and kpi.value is None
            assert kpi.reason is not None and "cu.genlog.jsonl 없음" in kpi.reason

    def test_corrupt_line_is_unmeasured(self, tmp_path: Path) -> None:
        dirs = _copy_seats(tmp_path)
        path = dirs[0] / "cu.genlog.jsonl"
        original = path.read_bytes()
        path.write_bytes(original + b"{broken\n")
        assert path.read_bytes() != original
        kpi = _rework(dirs)
        assert kpi.measured is False
        assert kpi.reason is not None and "JSON 파싱 실패" in kpi.reason


# ──────────────────────────────────────────────────────────────────────
# ④ 원장 레코드 모양
# ──────────────────────────────────────────────────────────────────────
class TestRecordShape:
    def test_detail_only_on_the_two_kpis(self, tmp_path: Path) -> None:
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
        assert sum(v["measured"] for v in kpis.values()) == 6
        for name, value in kpis.items():
            has_detail = "detail" in value
            assert has_detail == (name in {"auto_gate_pass_rate", "rework_rate"}), name
        assert set(kpis["hit_seconds"]) == {"measured", "value", "unit", "reason"}

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
