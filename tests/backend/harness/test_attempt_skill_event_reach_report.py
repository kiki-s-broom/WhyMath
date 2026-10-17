"""EOS-57 ② 기록률 리포트 — 순수 집계·렌더 계약 (hermetic·DB 없이).

이 리포트의 존재 이유는 "좌석과 writer를 만들었다"가 "작동한다"의 증거가 아니기 때문이다
(CLAUDE.md 「작동 신호 없는 알고리즘 부착 금지」). 따라서 테스트도 *숫자가 나온다*가 아니라
**혼동을 막는 변별력**을 본다:

  ① 분모 0을 0%로 위장하지 않는다(측정 불가와 미달은 다른 사실).
  ② writer 미도달(이벤트 없음)과 해소 0건(`[]`)이 다른 칸에 렌더된다.
  ③ 죽은 채점 경로가 화면에서 *사라지지 않는다*(폐쇄 3종 전부 보강 — group by 결과에 행이
     없으면 0%로 보여야지 행 자체가 없어지면 전멸이 안 보인다).
  ④ 게이트가 아니다 — 0%가 exit 1을 내지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import whymath_backend.harness.attempt_skill_event_reach_report as asr
from whymath_backend.harness.attempt_skill_event_reach_report import (
    RecordingCounts,
    build_report,
    dump_json,
    parse_since,
    render_report,
    report_to_json,
)


def _counts(**over: object) -> RecordingCounts:
    base: dict[str, object] = {
        "attempts_total": 10,
        "events_total": 8,
        "events_null_skill_ids": 0,
        "events_empty_skill_ids": 3,
        "events_nonempty_skill_ids": 5,
        "events_by_source": {"attempt_submit": 8},
        "nonempty_by_source": {"attempt_submit": 5},
    }
    base.update(over)
    return RecordingCounts(**base)  # type: ignore[arg-type]


class TestRates:
    def test_three_rates_use_the_stated_denominators(self) -> None:
        """세 비율의 분모가 각각 attempt·이벤트·attempt — 뭉개면 원인 축을 못 가른다."""
        report = build_report(_counts())
        assert report.writer_reach_rate == pytest.approx(8 / 10)  # 배선 축
        assert report.resolution_rate == pytest.approx(5 / 8)  # 데이터 축
        assert report.end_to_end_rate == pytest.approx(5 / 10)  # 종단

    def test_zero_denominator_is_none_not_zero(self) -> None:
        """① 분모 0 → None. "측정 불가"와 "0%"는 다른 사실이다(0으로 위장 금지)."""
        report = build_report(
            _counts(
                attempts_total=0,
                events_total=0,
                events_empty_skill_ids=0,
                events_nonempty_skill_ids=0,
                events_by_source={},
                nonempty_by_source={},
            )
        )
        assert report.writer_reach_rate is None
        assert report.resolution_rate is None
        assert report.end_to_end_rate is None
        assert "측정 불가(분모 0)" in render_report(report)
        assert "0.0%" not in render_report(report)

    def test_unreached_and_empty_resolution_are_separate_cells(self) -> None:
        """② 미도달(10-8=2)과 해소 0건(3)이 각각 다른 숫자로 렌더된다."""
        rendered = render_report(build_report(_counts()))
        assert "| writer 미도달 | 2 |" in rendered
        assert "| 기록·해소 0건 | 3 |" in rendered
        assert "| 기록·해소 ≥1 | 5 |" in rendered


class TestSourceBreakdown:
    def test_dead_path_is_rendered_as_zero_not_omitted(self) -> None:
        """③ coach_completion 행이 DB에 0건이어도 표에서 사라지지 않는다.

        group by 결과만 렌더하면 한 경로의 writer가 통째로 죽었을 때 그 경로가 화면에서
        *사라져* 전멸이 안 보인다 — 폐쇄 3종 보강이 그것을 막는다. 새 경로(EOS-146의
        `coach_wrong_submission`)도 같은 보강을 받는다 — 앱 오답이 원장에 안 닿는 전멸이
        이 화면에서 0으로 보여야 한다.
        """
        report = build_report(_counts())
        assert [b.source for b in report.sources] == [
            "attempt_submit",
            "coach_completion",
            "coach_wrong_submission",
        ]
        dead = next(b for b in report.sources if b.source == "coach_completion")
        assert dead.events == 0
        assert dead.nonempty_rate is None  # 분모 0 → 측정 불가(0%가 아니다)
        rendered = render_report(report)
        assert "`coach_completion` | 0 |" in rendered
        assert "`coach_wrong_submission` | 0 |" in rendered

    def test_unknown_source_label_is_kept_not_dropped(self) -> None:
        """미지 라벨(구판·오배선)도 버리지 않는다 — 조용한 생략은 사실 은폐다."""
        report = build_report(
            _counts(
                events_by_source={"attempt_submit": 6, "legacy_path": 2},
                nonempty_by_source={"attempt_submit": 5},
            )
        )
        assert [b.source for b in report.sources] == [
            "attempt_submit",
            "coach_completion",
            "coach_wrong_submission",
            "legacy_path",
        ]

    def test_missing_source_key_renders_as_placeholder(self) -> None:
        """`event_data.source` 없는 기록은 `(미기재)`로 렌더된다(계약상 required라 이상 신호)."""
        report = build_report(_counts(events_by_source={"": 8}, nonempty_by_source={"": 5}))
        assert "`(미기재)` | 8 |" in render_report(report)


class TestWindowSkew:
    def test_more_events_than_attempts_is_flagged_not_silently_clamped(self) -> None:
        """이벤트 > attempt이면 클램프 사실을 경고로 말한다 — 조용한 0은 분모 왜곡을 숨긴다."""
        rendered = render_report(build_report(_counts(attempts_total=3, events_total=8)))
        assert "창 경계 왜곡" in rendered
        assert "| writer 미도달 | 0 |" in rendered

    def test_normal_case_has_no_skew_warning(self) -> None:
        """변별력 — 정상 상태(attempt ≥ 이벤트)에서는 경고가 뜨지 않는다."""
        assert "창 경계 왜곡" not in render_report(build_report(_counts()))


class TestPathologyVisibility:
    def test_null_skill_ids_events_are_surfaced(self) -> None:
        """이벤트는 있는데 skill_ids가 NULL인 병리가 표에 뜬다 — 조용히 넘기지 않는다."""
        rendered = render_report(build_report(_counts(events_null_skill_ids=4)))
        assert "이벤트 있으나 skill_ids NULL | 4 |" in rendered


class TestSerialization:
    def test_json_round_trip_carries_rates_and_sources(self) -> None:
        report = build_report(_counts(), since=datetime(2026, 9, 1, tzinfo=UTC))
        payload = report_to_json(report)
        assert payload["since"] == "2026-09-01T00:00:00+00:00"
        assert payload["events_nonempty_skill_ids"] == 5
        assert payload["end_to_end_rate"] == pytest.approx(0.5)
        assert {s["source"] for s in payload["sources"]} == {
            "attempt_submit",
            "coach_completion",
            "coach_wrong_submission",
        }
        assert dump_json(report).endswith("\n")

    def test_report_states_it_is_not_a_gate(self) -> None:
        """④ 게이트가 아님을 리포트 본문이 스스로 말한다(임계 없는 차단 금지)."""
        assert "exit 게이트가 아니다" in render_report(build_report(_counts()))


class TestSinceParsing:
    def test_naive_input_is_interpreted_as_utc(self) -> None:
        assert parse_since("2026-09-01") == datetime(2026, 9, 1, tzinfo=UTC)

    def test_aware_input_is_preserved(self) -> None:
        assert parse_since("2026-09-01T00:00:00+09:00").utcoffset() is not None

    def test_bad_input_raises_instead_of_silent_full_window(self) -> None:
        """파싱 실패는 예외 — 조용히 "전체 창"으로 폴백하면 관측 대상이 바뀐 걸 아무도 모른다."""
        with pytest.raises(ValueError):
            parse_since("작년쯤")


class TestCliFailurePath:
    """측정 실패가 "0% 미달"로 위장되지 않는지 — 2026-08-22 수집 도구 설계 규칙."""

    def test_db_failure_exits_2_with_exception_type_in_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DB 오류 → exit 2 + **예외 타입명**. 무타입 경고는 8개의 실패를 한 글자로 만든다."""
        with patch.object(asr, "_run", new=AsyncMock(side_effect=RuntimeError("접속 실패"))):
            exit_code = asr.main([])
        assert exit_code == asr._EXIT_INPUT_ERROR
        assert "RuntimeError" in capsys.readouterr().err

    def test_success_path_exits_0_even_at_zero_percent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """변별력 — 기록률 0%도 exit 0(게이트 아님). 실패(2)와 0%(0)가 다른 코드여야 한다."""
        empty = build_report(
            _counts(
                attempts_total=0,
                events_total=0,
                events_empty_skill_ids=0,
                events_nonempty_skill_ids=0,
                events_by_source={},
                nonempty_by_source={},
            )
        )
        with patch.object(asr, "_run", new=AsyncMock(return_value=empty)):
            assert asr.main([]) == 0
        assert "기록률 리포트" in capsys.readouterr().out

    def test_json_artifact_is_written_to_requested_path(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "eos57.json"
        with patch.object(asr, "_run", new=AsyncMock(return_value=build_report(_counts()))):
            assert asr.main(["--json", str(out)]) == 0
        assert "end_to_end_rate" in out.read_text(encoding="utf-8")
