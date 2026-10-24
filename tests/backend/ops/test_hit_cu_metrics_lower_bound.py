"""HIT 하한 가드 — 비현실적으로 짧은 검수의 가시화·게이트 방향 대칭 (OPS-90).

정본: `ops/hit_cu_metrics.py` 모듈 docstring "HIT 하한 가드". 배경: `--max-median-minutes`는
상한만 봐서 경과가 0초에 가까울수록 무조건 통과했다 — 2026-09-22 카나리 회차(중앙값 6초·
P90 41초·총합 246초, 재입력 세션이라 무효로 자인)가 "목표 대비 40배 달성"으로만 읽혔다.

검증 설계(정상 입력의 초록은 보호의 증거가 아니다):
  - **분기별 원인 열거 + 성공 방향 대조군** — 각 분기마다 "그 절이 없으면 통과해 버리는 입력"
    을 픽스처로 둔다. 하한 경계(미만/정확히/초과), 다세션 합산, 미계측·미종결·anomaly 제외,
    표본 0건, 과반 미만/정확히 절반/과반 이상, 가드 끔, 인자 오류가 그 분기다.
  - **게이트 양방향** — 같은 입력이 하한 가드 유무(`--min-plausible-seconds 0`)로 exit 0↔1
    로 뒤집힘을 보인다(가드가 일한 증거) + 정상 표본은 가드가 있어도 exit 0(과잉 차단 없음).
  - **재현 픽스처** — 2026-09-22 회차의 공개된 요약 수치 3개(중앙값 6초·P90 41초·총합 246초)에
    맞춘 *재구성* 15건. 원 이벤트는 코퍼스 데이터라 저장소에 없으므로 CU별 값은 재구성이다.
  - **소비자** — 주간 KPI(`weekly_metrics_report`)와 스코어카드 어댑터가 하한 가드에 걸린
    회차를 `measured: true`로 계상하지 않는다(감리 W-04).

hermetic — tmp_path·픽스처만.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from whymath_backend.harness.review_timer import (
    abort_review,
    append_event_jsonl,
    finish_review,
    start_review,
)
from whymath_backend.ops import validation_scorecard as vs
from whymath_backend.ops.hit_cu_metrics import (
    DEFAULT_MIN_PLAUSIBLE_SECONDS,
    HitCuReport,
    aggregate,
    main,
    render_report,
)
from whymath_backend.ops.weekly_metrics_report import build_record_from_report
from whymath_backend.schema.review_timer import ReviewTimerEvent

_T0 = datetime(2026, 10, 24, 2, 0, tzinfo=UTC)
_FLOOR_MS = int(DEFAULT_MIN_PLAUSIBLE_SECONDS * 1000)  # 30_000


def _cu(
    slug: str,
    elapsed_ms: int | None,
    *,
    started_at: datetime = _T0,
    finished_at: datetime = _T0,
) -> list[ReviewTimerEvent]:
    """CU 1개를 1세션으로 검수한 이벤트 쌍(started+finished)."""
    started = start_review(cu_slug=slug, reviewer_id="kiki", occurred_at=started_at)
    finished = finish_review(
        review_session_id=started.review_session_id,
        cu_slug=slug,
        reviewer_id="kiki",
        verdict="approved",
        elapsed_ms=elapsed_ms,
        occurred_at=finished_at,
    )
    return [started, finished]


def _many(elapsed_ms_list: list[int]) -> list[ReviewTimerEvent]:
    """CU N개 — slug는 cu-0..N-1, 경과는 주어진 순서대로(전건 계측 성립)."""
    events: list[ReviewTimerEvent] = []
    for idx, elapsed in enumerate(elapsed_ms_list):
        events += _cu(f"cu-{idx}", elapsed)
    return events


def _write_events(path: Path, events: list[ReviewTimerEvent]) -> None:
    for event in events:
        append_event_jsonl(path, event)


def _report(elapsed_ms_list: list[int], **kwargs: float) -> HitCuReport:
    return aggregate(_many(elapsed_ms_list), **kwargs)


class TestFloorBoundaryPerCu:
    """하한 경계 — '미만'만 센다. 각 값이 그 절의 반례다."""

    def test_default_floor_is_documented_constant(self) -> None:
        """기본값이 조용히 바뀌면 이 테스트가 깨진다 — 바꾸려면 docstring 근거도 함께."""
        assert DEFAULT_MIN_PLAUSIBLE_SECONDS == 30.0
        assert _report([60_000]).min_plausible_seconds == 30.0

    @pytest.mark.parametrize(
        ("elapsed_ms", "implausible"),
        [
            (0, True),  # 0초 — 이 가드의 존재 이유
            (6_000, True),  # 2026-09-22 회차의 중앙값
            (_FLOOR_MS - 1_000, True),  # 하한-1초
            (_FLOOR_MS - 1, True),  # 하한-1ms (부동소수 경계)
            (_FLOOR_MS, False),  # 정확히 하한 — 미만이 아니므로 현실적
            (_FLOOR_MS + 1_000, False),  # 하한+1초
            (240_000, False),  # 목표 중앙값 4분
        ],
    )
    def test_single_cu_boundary(self, elapsed_ms: int, implausible: bool) -> None:
        report = _report([elapsed_ms])
        assert report.cu_measured == 1
        assert report.cu_implausible_short_count == (1 if implausible else 0)
        # n=1이면 1건이 곧 100%·0건이 0% — 경계 분기가 majority로 그대로 드러난다.
        assert report.hit_implausible_majority is implausible
        assert report.implausible_short_share == (1.0 if implausible else 0.0)

    def test_custom_floor_moves_the_boundary(self) -> None:
        """하한 인자가 실제로 판정에 쓰인다 — 같은 6초가 하한 5초에서는 현실적(대조군)."""
        assert _report([6_000]).hit_implausible_majority is True
        assert _report([6_000], min_plausible_seconds=5.0).hit_implausible_majority is False
        assert _report([6_000], min_plausible_seconds=6.0).hit_implausible_majority is False
        assert _report([6_000], min_plausible_seconds=6.001).hit_implausible_majority is True


class TestCuLevelNotSessionLevel:
    """판정 단위는 CU의 경과 합(HIT 정의)이다 — 세션 단위로 세면 다세션 CU를 잘못 거른다."""

    def test_two_short_sessions_summing_to_plausible_is_not_flagged(self) -> None:
        # 20s + 20s = 40s ≥ 30s. 세션 단위 판정이면 둘 다 하한 미만이라 오탐된다.
        events = _cu("cu-x", 20_000) + _cu("cu-x", 20_000)
        report = aggregate(events)
        assert report.cu_measured == 1
        assert report.hit_median_seconds == 40.0
        assert report.cu_implausible_short_count == 0
        assert report.hit_implausible_majority is False

    def test_two_short_sessions_summing_below_floor_is_flagged(self) -> None:
        # 10s + 10s = 20s < 30s — 대조군(합산해도 하한 미만이면 걸린다).
        report = aggregate(_cu("cu-x", 10_000) + _cu("cu-x", 10_000))
        assert report.hit_median_seconds == 20.0
        assert report.cu_implausible_short_count == 1
        assert report.hit_implausible_majority is True


class TestMajorityBranches:
    """절반 이상(`2*k >= n`) 판정 — 과반 미만/정확히 절반/과반 이상 전 분기."""

    SHORT = 5_000
    OK = 120_000

    @pytest.mark.parametrize(
        ("k", "n", "expected"),
        [
            (0, 3, False),  # 하나도 없음
            (1, 3, False),  # 과반 미만(33%)
            (1, 4, False),  # 과반 미만(25%)
            (2, 4, True),  # 정확히 절반(짝수 n) — 중앙값이 이미 오염되는 경계
            (1, 2, True),  # n=2의 절반
            (2, 3, True),  # 과반(67%)
            (3, 4, True),  # 과반(75%)
            (4, 4, True),  # 전건 하한 미만
        ],
    )
    def test_share_boundaries(self, k: int, n: int, expected: bool) -> None:
        report = _report([self.SHORT] * k + [self.OK] * (n - k))
        assert report.cu_measured == n
        assert report.cu_implausible_short_count == k
        assert report.implausible_short_share == pytest.approx(k / n)
        assert report.hit_implausible_majority is expected

    def test_exactly_half_median_is_actually_contaminated(self) -> None:
        """정확히 절반 경계를 열어 두면 안 되는 이유 — 그 중앙값은 하한 미만 값과의 평균이다."""
        report = _report([self.SHORT, self.SHORT, self.OK, self.OK])
        assert report.hit_median_seconds == pytest.approx(
            (5.0 + 120.0) / 2
        )  # 62.5s: 하한 위로 보임
        assert report.hit_implausible_majority is True  # 그래도 경고 — 평균이 가린 것을 드러낸다


class TestUnmeasuredAreNotCounted:
    """모른다 ≠ 아니다 — 미계측·미종결·anomaly·표본 0건은 하한 미만으로도, 통과로도 세지 않는다."""

    def test_no_measured_cu_is_none_not_false(self) -> None:
        """전건 미계측 — 검사할 표본이 없다. False('검사했고 괜찮다')로 접으면 위장이다."""
        report = aggregate(_cu("cu-a", None) + _cu("cu-b", None))
        assert report.cu_measured == 0
        assert report.hit_implausible_majority is None
        assert report.implausible_short_share is None
        assert report.cu_implausible_short_count == 0

    def test_dangling_start_not_counted_as_short(self) -> None:
        events = [start_review(cu_slug="cu-d", reviewer_id="kiki")]
        report = aggregate(events)
        assert report.cu_measured == 0
        assert report.cu_implausible_short_count == 0
        assert report.hit_implausible_majority is None

    def test_aborted_only_cu_not_counted(self) -> None:
        started = start_review(cu_slug="cu-ab", reviewer_id="kiki")
        aborted = abort_review(
            review_session_id=started.review_session_id,
            cu_slug="cu-ab",
            reviewer_id="kiki",
            elapsed_ms=1_000,
        )
        report = aggregate([started, aborted])
        assert report.cu_measured == 0  # finished 없음 = 미종결 — HIT 표본이 아니다
        assert report.cu_implausible_short_count == 0
        assert report.hit_implausible_majority is None

    def test_unmeasured_cu_excluded_from_denominator(self) -> None:
        """분모는 계측 CU만 — 미계측 3건이 섞여도 계측 2건 중 1건(50%)이 그대로 판정된다."""
        events = _cu("cu-ok", 120_000) + _cu("cu-short", 5_000)
        events += _cu("cu-u1", None) + _cu("cu-u2", None) + _cu("cu-u3", None)
        report = aggregate(events)
        assert report.cu_measured == 2
        assert report.cu_unmeasured == 3
        assert report.implausible_short_share == pytest.approx(0.5)
        assert report.hit_implausible_majority is True
        # 분모가 전체 CU(5)였다면 20%로 과반 미만이 되어 경고가 꺼진다 — 그 반례.
        assert report.cu_total == 5

    def test_anomaly_session_with_short_elapsed_not_counted(self) -> None:
        """복수 종결 세션은 measured 불성립 강등 — 짧은 경과 합이어도 하한 표본에 안 들어온다."""
        started = start_review(cu_slug="cu-an", reviewer_id="kiki")
        first = finish_review(
            review_session_id=started.review_session_id,
            cu_slug="cu-an",
            reviewer_id="kiki",
            verdict="approved",
            elapsed_ms=1_000,
        )
        second = finish_review(
            review_session_id=started.review_session_id,
            cu_slug="cu-an",
            reviewer_id="kiki",
            verdict="approved",
            elapsed_ms=1_000,
        )
        report = aggregate([started, first, second] + _cu("cu-ok", 120_000))
        assert report.session_anomaly_count == 1
        assert report.cu_measured == 1
        assert report.cu_implausible_short_count == 0
        assert report.hit_implausible_majority is False


class TestInvalidElapsedInputs:
    def test_negative_elapsed_cannot_enter_through_schema(self) -> None:
        """음수 경과는 스키마(ge=0)가 입구에서 막는다 — 집계에 도달하지 못한다."""
        started = start_review(cu_slug="cu-n", reviewer_id="kiki")
        with pytest.raises(ValidationError):
            finish_review(
                review_session_id=started.review_session_id,
                cu_slug="cu-n",
                reviewer_id="kiki",
                verdict="approved",
                elapsed_ms=-1,
            )

    def test_negative_elapsed_line_in_file_is_parse_failure_exit1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """파일 경로로 들어온 음수도 파싱 실패 → 부분 입력 판정 금지(exit 1) — 가드가 삼키지 않는다."""
        path = tmp_path / "events.jsonl"
        events = _many([120_000, 120_000])
        _write_events(path, events)
        bad = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        bad["event_id"] = str(uuid.uuid4())
        bad["elapsed_ms"] = -5
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(bad) + "\n")
        assert main(["--events", str(path), "--max-median-minutes", "4"]) == 1
        assert "파싱 실패" in capsys.readouterr().err

    def test_timestamp_reversal_does_not_change_the_decision(self) -> None:
        """finished.occurred_at < started.occurred_at(타임스탬프 역전) — 경과 판정은 계측값
        `elapsed_ms`만 본다(타임스탬프는 귀속 시각용이지 경과 산식이 아니다). 역전이 있어도
        긴 계측은 현실적, 짧은 계측은 하한 미만 — 시각으로 경과를 재계산하지 않는다."""
        reversed_long = _cu("cu-r1", 120_000, started_at=_T0, finished_at=_T0 - timedelta(hours=1))
        reversed_short = _cu("cu-r2", 5_000, started_at=_T0, finished_at=_T0 - timedelta(hours=1))
        assert aggregate(reversed_long).hit_implausible_majority is False
        assert aggregate(reversed_short).hit_implausible_majority is True
        # 대조군: 같은 값이 정상 순서(역전 없음)일 때와 판정이 같다.
        assert aggregate(_cu("cu-n1", 5_000)).hit_implausible_majority is True

    def test_nan_floor_rejected_because_it_would_silently_disable_the_guard(self) -> None:
        with pytest.raises(ValueError, match="NaN"):
            aggregate(_many([5_000]), min_plausible_seconds=math.nan)


class TestGuardDisabledAndZeroSample:
    def test_floor_zero_turns_guard_off_as_unknown_not_ok(self) -> None:
        """하한 0 = 가드 끔 — 0초 CU도 걸리지 않고, 'False(괜찮다)'가 아니라 None(미검사)."""
        report = _report([0, 0, 0], min_plausible_seconds=0.0)
        assert report.cu_measured == 3
        assert report.cu_implausible_short_count == 0
        assert report.hit_implausible_majority is None
        text = render_report(report)
        assert "꺼짐" in text  # 끈 사실이 리포트에 보인다(조용한 비활성 금지)

    def test_zero_events_all_unfinished_has_no_majority(self) -> None:
        report = aggregate([start_review(cu_slug="cu-z", reviewer_id="kiki")])
        assert report.hit_implausible_majority is None
        assert "미산출(계측 CU 0건)" in render_report(report)


class TestRenderWarningNextToMedian:
    def test_flagged_report_marks_median_line_and_prints_warning(self) -> None:
        text = render_report(_report([5_000, 6_000, 8_000]))
        median_line = next(line for line in text.splitlines() if line.startswith("- 중앙값"))
        assert "신뢰 불가" in median_line  # 중앙값 줄 *옆*에 붙는다
        # 별도 경고 줄(중앙값 줄의 표식과는 다른 줄) — 표식만으로는 이유·행동이 안 보인다.
        warning_lines = [line for line in text.splitlines() if line.startswith("- ⚠ **경고")]
        assert len(warning_lines) == 1
        assert "절반 이상" in warning_lines[0]
        assert "HIT 달성 근거로 쓰지 말고" in warning_lines[0]
        assert "3건 중 3건" in text

    def test_normal_report_has_count_line_but_no_warning(self) -> None:
        """성공 방향 대조군 — 정상 표본에는 건수 줄만 있고 경고·마크가 없다."""
        text = render_report(_report([120_000, 180_000, 240_000]))
        median_line = next(line for line in text.splitlines() if line.startswith("- 중앙값"))
        assert "신뢰 불가" not in median_line
        assert "경고" not in text
        assert not [line for line in text.splitlines() if line.startswith("- ⚠")]
        assert "3건 중 0건" in text  # 가시화 자체는 정상일 때도 한다

    def test_minority_short_shows_count_without_warning(self) -> None:
        text = render_report(_report([5_000, 120_000, 180_000, 240_000]))
        assert "4건 중 1건" in text
        assert "경고" not in text


def _canary_replay_ms() -> list[int]:
    """2026-09-22 카나리 회차의 *재구성* 15건 — 공개된 요약 3수치에 맞춘 값.

    중앙값 6초·P90 41초·총합 246초(4분 6초). CU별 원 값은 코퍼스 데이터라 저장소에 없다 —
    아래는 그 3수치를 만족하는 한 가지 분포일 뿐이며 원 분포가 아니다(최댓값 102초는 총합을
    맞추려 정한 값). 가드는 '중앙값이 하한의 1/5'인 이 모양을 걸러야 한다.
    """
    seconds = [2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 8, 9, 41, 41, 102]
    return [s * 1000 for s in seconds]


class TestCanaryReplay:
    def test_replay_matches_the_published_summary(self) -> None:
        """재구성의 자기 검증 — 요약 3수치(중앙값 6·P90 41·총합 246)와 일치해야 재현 픽스처다."""
        report = _report(_canary_replay_ms(), min_plausible_seconds=0.0)
        assert report.cu_measured == 15
        assert report.hit_median_seconds == 6.0
        assert report.hit_p90_seconds == pytest.approx(41.0)
        assert report.hit_total_seconds == 246.0

    def test_replay_is_flagged(self) -> None:
        report = _report(_canary_replay_ms())
        assert report.cu_implausible_short_count == 12  # 41초 2건·102초 1건만 하한 이상
        assert report.hit_implausible_majority is True

    def test_replay_gate_flips_with_guard_on_off(self, tmp_path: Path) -> None:
        """이 도구의 옛 동작을 재현 — 가드를 끄면 6초 중앙값이 게이트(4분 이하)를 통과한다."""
        path = tmp_path / "canary.jsonl"
        _write_events(path, _many(_canary_replay_ms()))
        args = ["--events", str(path), "--max-median-minutes", "4", "--max-p90-minutes", "8"]
        assert main([*args, "--min-plausible-seconds", "0"]) == 0  # 옛 동작: 40배 달성으로 통과
        assert main(args) == 1  # 가드 on(기본): 걸린다


class TestCliGate:
    def test_median_gate_fail_closed_when_majority_implausible(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([5_000, 6_000, 8_000]))
        assert main(["--events", str(path), "--max-median-minutes", "4"]) == 1
        err = capsys.readouterr().err
        assert "[게이트 FAIL]" in err
        assert "HIT 하한 가드" in err
        assert "[OK]" not in err

    def test_p90_gate_fail_closed_when_majority_implausible(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([5_000, 6_000, 8_000]))
        assert main(["--events", str(path), "--max-p90-minutes", "8"]) == 1

    def test_same_input_passes_when_guard_disabled(self, tmp_path: Path) -> None:
        """가드가 뒤집은 것임을 보이는 쌍 — 하한 0이면 같은 입력이 옛 동작대로 통과한다."""
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([5_000, 6_000, 8_000]))
        assert main(["--events", str(path), "--max-median-minutes", "4"]) == 1
        assert (
            main(
                ["--events", str(path), "--max-median-minutes", "4", "--min-plausible-seconds", "0"]
            )
            == 0
        )

    def test_normal_sample_passes_gate_control(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """성공 방향 대조군 — 정상 표본은 가드가 있어도 통과한다(과잉 차단 없음)."""
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([120_000, 180_000, 200_000]))
        assert main(["--events", str(path), "--max-median-minutes", "4"]) == 0
        err = capsys.readouterr().err
        assert "[OK]" in err
        assert "경고" not in err

    def test_minority_short_still_passes_gate_control(self, tmp_path: Path) -> None:
        """과반 미만(1/4)은 경고·차단 대상이 아니다 — 소수의 빠른 검수를 이유로 회차를 버리지 않는다."""
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([5_000, 120_000, 180_000, 200_000]))
        assert main(["--events", str(path), "--max-median-minutes", "4"]) == 0

    def test_measurement_only_run_warns_but_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """게이트 미지정(계측 전용) — 측정은 성립하므로 exit 0, 그러나 경고는 낸다."""
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([5_000, 6_000, 8_000]))
        assert main(["--events", str(path)]) == 0
        captured = capsys.readouterr()
        assert "[경고]" in captured.err
        assert "신뢰 불가" in captured.out

    def test_coverage_only_gate_is_not_a_hit_gate(self, tmp_path: Path) -> None:
        """--min-coverage는 HIT 게이트가 아니다 — 하한 가드가 적재율 게이트를 막지 않는다."""
        events_path = tmp_path / "events.jsonl"
        events = _many([5_000, 6_000, 8_000])
        _write_events(events_path, events)
        verdicts = tmp_path / "verdicts.jsonl"
        verdicts.write_text(
            "".join(
                json.dumps({"slug": f"cu-{i}", "review_status": "approved"}) + "\n"
                for i in range(3)
            ),
            encoding="utf-8",
        )
        assert (
            main(
                ["--events", str(events_path), "--verdicts", str(verdicts), "--min-coverage", "0.1"]
            )
            == 0
        )

    def test_guard_off_prints_warning_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([5_000]))
        assert main(["--events", str(path), "--min-plausible-seconds", "0"]) == 0
        assert "가드가 꺼져" in capsys.readouterr().err

    @pytest.mark.parametrize("bad", ["nan", "-1", "inf", "-0.5"])
    def test_invalid_floor_argument_rejected(self, tmp_path: Path, bad: str) -> None:
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([60_000]))
        with pytest.raises(SystemExit) as excinfo:
            main(["--events", str(path), "--min-plausible-seconds", bad])
        assert excinfo.value.code == 2

    def test_json_output_carries_guard_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "events.jsonl"
        _write_events(path, _many([5_000, 6_000, 120_000]))
        assert main(["--events", str(path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["min_plausible_seconds"] == 30.0
        assert payload["cu_implausible_short_count"] == 2
        assert payload["hit_implausible_majority"] is True
        assert payload["implausible_short_share"] == pytest.approx(2 / 3)


_WEEK_START = datetime(2026, 10, 19, tzinfo=UTC)
_WEEK_END = datetime(2026, 10, 26, tzinfo=UTC)


class TestConsumerWeeklyKpi:
    """감리 W-04 — 하한 가드에 걸린 회차를 `measured: true`로 계상하지 않는다."""

    def _record(self, report: HitCuReport):  # type: ignore[no-untyped-def]
        return build_record_from_report(
            report,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            generated_at=_WEEK_END,
            krw_per_usd=1400.0,
        )

    def test_implausible_majority_hit_and_throughput_are_unmeasured(self) -> None:
        record = self._record(_report(_canary_replay_ms()))
        for name in ("hit_seconds", "throughput_cu_per_hour"):
            kpi = record.kpis[name]
            assert kpi.measured is False, name
            assert kpi.value is None, name
            assert kpi.reason and "하한" in kpi.reason, name

    def test_normal_sample_stays_measured_control(self) -> None:
        record = self._record(_report([120_000, 180_000, 240_000]))
        assert record.kpis["hit_seconds"].measured is True
        assert record.kpis["hit_seconds"].value == 180.0
        assert record.kpis["throughput_cu_per_hour"].measured is True

    def test_minority_short_stays_measured_control(self) -> None:
        record = self._record(_report([5_000, 120_000, 180_000, 240_000]))
        assert record.kpis["hit_seconds"].measured is True

    def test_guard_off_none_keeps_legacy_behavior(self) -> None:
        """가드 끔(None)은 '걸렸다'가 아니다 — 소비자가 None을 True로 접으면 안 된다."""
        report = _report([5_000, 6_000], min_plausible_seconds=0.0)
        assert report.hit_implausible_majority is None
        assert self._record(report).kpis["hit_seconds"].measured is True


def _scorecard_json(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "hit_median_seconds": 6.0,
        "hit_total_seconds": 246.0,
        "cu_measured": 15,
        "rejected_count": 0,
        "failure_code_counts": {},
    }
    base.update(overrides)
    return base


class TestConsumerScorecardAdapter:
    def test_majority_true_drops_hit_and_throughput(self) -> None:
        out = vs.adapt_hit_cu_metrics(_scorecard_json(hit_implausible_majority=True))
        assert "hit" not in out
        assert "throughput" not in out

    def test_majority_false_keeps_hit_control(self) -> None:
        out = vs.adapt_hit_cu_metrics(_scorecard_json(hit_implausible_majority=False))
        assert out["hit"]["median_minutes"] == pytest.approx(0.1)
        assert "throughput" in out

    def test_missing_key_old_artifact_keeps_hit(self) -> None:
        """가드 이전에 만든 옛 JSON(키 없음)은 종전대로 — 키 부재를 '걸렸다'로 읽지 않는다."""
        out = vs.adapt_hit_cu_metrics(_scorecard_json())
        assert "hit" in out

    def test_majority_none_keeps_hit(self) -> None:
        out = vs.adapt_hit_cu_metrics(_scorecard_json(hit_implausible_majority=None))
        assert "hit" in out
