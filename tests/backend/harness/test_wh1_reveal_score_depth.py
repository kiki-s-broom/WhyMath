"""⑧ 답 미루기 도달 깊이 — S4-11 reveal_score 정밀화(KPI '도달 깊이 2.5+' 측정 기반·S3-04 연동).

value(평균 hint_level)는 **바뀌지 않아야** 하고(KPI 정의 불변), 같은 힌트제공 행의 `reveal_score`
(검수 graded 힌트가 실제로 서빙된 턴만 존재)는 note에 기록 비율·평균·깊이 환산으로 병기돼야 한다.
기록 0건도 숨기지 않는다("작동한 비율" — 카탈로그 서빙이 한 번도 없었다는 사실이 보여야 한다).
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from whymath_backend.harness.wh1_evaluation import (
    MetricStatus,
    _hint_depth_from_levels,
    compute_wh1_surrogate_metrics,
)

from .test_wh1_evaluation import _FakeScalarResult, _make_session

# `_make_session`의 execute 큐에서 ⑤⑧ 힌트 행이 놓이는 자리(그 모듈 `_FakeSession` docstring 5번).
_HINT_ROWS_INDEX = 4


class TestHintDepthRevealNote:
    def test_value_is_unchanged_and_reveal_scores_are_reported(self) -> None:
        m = _hint_depth_from_levels([1, 2, 3], [1 / 3, 2 / 3])
        assert m.status is MetricStatus.MEASURED
        assert m.value == pytest.approx(2.0)  # KPI 정의(평균 hint_level) 불변
        assert "reveal_score 기록 2/3건" in m.note
        assert "평균 0.5000" in m.note
        assert "깊이 환산 1.5000" in m.note  # 3 × 0.5

    def test_zero_recorded_is_stated_not_hidden(self) -> None:
        m = _hint_depth_from_levels([2, 2])
        assert m.value == pytest.approx(2.0)
        assert "reveal_score 기록 0/2건" in m.note

    def test_no_hint_events_stays_no_data(self) -> None:
        m = _hint_depth_from_levels([], [1.0])
        assert m.status is MetricStatus.NO_DATA and m.value is None


async def test_compute_reads_reveal_score_from_the_same_hint_rows() -> None:
    """compute가 힌트제공 행의 3번째 열(reveal_score)을 새 쿼리 없이 읽어 note에 싣는다."""
    session = _make_session(
        total_sessions=1,
        completed_sessions=1,
        avg_tokens=None,
        token_sample=0,
        hint_levels=[1, 2, 3],
    )
    fake = cast(Any, session)
    fake._results[_HINT_ROWS_INDEX] = _FakeScalarResult(
        all_rows=[(1, None, None), (2, False, 2 / 3), (3, None, 1.0)]
    )
    m = await compute_wh1_surrogate_metrics(session)
    assert m.hint_depth_reached.value == pytest.approx(2.0)
    assert "reveal_score 기록 2/3건" in m.hint_depth_reached.note
    assert "깊이 환산 2.5000" in m.hint_depth_reached.note  # (2/3 + 1) / 2 × 3
    assert m.sample_hint_events == 3


async def test_legacy_two_column_rows_count_as_unrecorded() -> None:
    """구 행 형태(2열)는 기록 없음으로 읽는다 — 3번째 열 부재로 터지지 않는다."""
    session = _make_session(
        total_sessions=1,
        completed_sessions=1,
        avg_tokens=None,
        token_sample=0,
        hint_levels=[2, 3],
    )
    m = await compute_wh1_surrogate_metrics(session)
    assert "reveal_score 기록 0/2건" in m.hint_depth_reached.note
