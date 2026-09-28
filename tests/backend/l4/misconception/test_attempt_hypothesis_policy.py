"""EOS-123 — 채점 1회차의 가설 행동 정책(정오답 × 훑기 3상태) 단위 계약.

기대값은 모듈의 표(`ATTEMPT_HYPOTHESIS_POLICY`)를 import하지 않고 **리터럴**로 적는다. 표를
import해서 기대값을 만들면 표를 잘못 바꾼 뮤테이션이 테스트 기대값도 함께 바꿔 살아남는다
(MISC-30 교훈 — 상수를 import한 테스트는 상수 뮤테이션을 따라 움직인다).

배선(핸들러가 이 값대로 `apply_candidates`를 부르는가)은 `tests/backend/api/test_me.py`의
`TestAttemptCorrectAnswerHypothesis`가, 감쇠 수치는 실 PG 테스트가 본다.
"""

from __future__ import annotations

from typing import Any

import pytest

from whymath_backend.l4.misconception.attempt_hypothesis_policy import (
    ATTEMPT_HYPOTHESIS_POLICY,
    AttemptHypothesisAction,
    decide_attempt_hypothesis_action,
)
from whymath_backend.schema.assessment_evidence import MisconceptionScan

_ALL_SCANS = tuple(MisconceptionScan)


@pytest.mark.parametrize(
    ("is_correct", "scan", "expected"),
    [
        # 오답 — 현행 그대로(훑었으면 반영 · 못 훑었으면 무변화).
        (False, "ran_with_candidates", "apply"),
        (False, "ran_no_candidate", "apply"),
        (False, "not_run", "none"),
        # 정답 — EOS-123 신규 2칸 + 현행 1칸.
        (True, "ran_no_candidate", "decay_only"),
        (True, "ran_with_candidates", "hold_conflict"),
        (True, "not_run", "none"),
    ],
)
def test_six_cells(is_correct: bool, scan: str, expected: str) -> None:
    """6칸을 하나씩 — 값은 리터럴이라 표를 바꾼 뮤테이션이 여기서 드러난다."""
    action = decide_attempt_hypothesis_action(is_correct=is_correct, scan=MisconceptionScan(scan))
    assert action.value == expected


def test_table_covers_every_combination_exactly() -> None:
    """표가 (bool × 3상태) 6칸을 **정확히** 덮는다 — 빠진 칸을 기본값으로 메우지 않는다."""
    expected_keys = {(c, s) for c in (False, True) for s in _ALL_SCANS}
    assert set(ATTEMPT_HYPOTHESIS_POLICY) == expected_keys
    assert len(ATTEMPT_HYPOTHESIS_POLICY) == 6


def test_not_run_never_touches_hypotheses() -> None:
    """모듈 간 불변식 — `not_run`이면 정오답과 무관하게 가설 무변경.

    `config.py`·`learning_state_recommendation.py`(EOS-140)·`schema/assessment_evidence.py`가
    이 불변식에 기대어 추론한다. 정답 쪽을 넓히는 회귀(독립 비판 F7)가 여기서 먼저 깨진다.
    """
    for is_correct in (False, True):
        action = decide_attempt_hypothesis_action(
            is_correct=is_correct, scan=MisconceptionScan.NOT_RUN
        )
        assert action is AttemptHypothesisAction.NONE


def test_conflict_hold_only_for_correct_with_candidates() -> None:
    """보류는 "정답 보고 + 후보 있음" 한 칸뿐 — 오답의 후보는 보류가 아니라 반영이다."""
    holds = [
        key
        for key in ((c, s) for c in (False, True) for s in _ALL_SCANS)
        if decide_attempt_hypothesis_action(is_correct=key[0], scan=key[1])
        is AttemptHypothesisAction.HOLD_CONFLICT
    ]
    assert holds == [(True, MisconceptionScan.RAN_WITH_CANDIDATES)]


def test_only_apply_feeds_candidates_and_it_is_wrong_answers_only() -> None:
    """후보를 가설에 싣는(그리고 복습 코칭을 계산하는) 행동은 오답에만 나온다.

    정답이 `APPLY`가 되면 정답 답안에서 읽은 후보(실측 오탐 포함)가 가설을 **강화**한다.
    """
    for scan in _ALL_SCANS:
        action = decide_attempt_hypothesis_action(is_correct=True, scan=scan)
        assert action is not AttemptHypothesisAction.APPLY, scan


@pytest.mark.parametrize("bad", [None, 1, 0, "true", 1.0])
def test_non_bool_correctness_is_rejected(bad: Any) -> None:
    """정오답이 bool이 아니면 거부한다 — `None`(모름)을 오답으로 접지 않는다.

    `1`·`0`도 거부한다: dict 조회는 `1 == True`로 통과해 버리므로, 형 검사가 없으면 호출자
    실수가 조용히 어느 한 칸으로 접힌다.
    """
    with pytest.raises(TypeError):
        decide_attempt_hypothesis_action(is_correct=bad, scan=MisconceptionScan.RAN_NO_CANDIDATE)


def test_unknown_scan_state_fails_loudly() -> None:
    """표에 없는 훑기 상태는 `ValueError` — 새 상태가 생기면 조용히 한쪽으로 접지 않는다."""
    with pytest.raises(ValueError, match="정책 표에 없는"):
        decide_attempt_hypothesis_action(is_correct=True, scan="ran_later")  # type: ignore[arg-type]


def test_action_values_are_stable_strings() -> None:
    """행동 값은 로그·후속 측정(MISC-36 ①)의 키가 된다 — 문자열을 리터럴로 동결한다."""
    assert [a.value for a in AttemptHypothesisAction] == [
        "apply",
        "decay_only",
        "hold_conflict",
        "none",
    ]
