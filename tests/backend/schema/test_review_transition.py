"""검수 상태 전이 계약 동결 (ADMIN-07) — 기대표는 코드와 독립인 손으로 적은 리터럴이다.

기대값을 `_TRANSITIONS`에서 파생하면 표에 한 칸을 잘못 추가해도 테스트가 같이 따라가
통과한다(동어반복). 그래서 4 액션 × 5 상태 = 20칸을 **허용 4 · 불허 16**으로 직접 적는다.
`None`(미설정) 행이 전부 불허인 것이 "모른다 ≠ pending"의 동결이다.
"""

from __future__ import annotations

import pytest

from whymath_backend.schema.enums import ReviewStatus
from whymath_backend.schema.review_transition import (
    IllegalReviewTransition,
    ReviewTransitionAction,
    action_requires_reason,
    allowed_actions,
    resolve_review_transition,
)

P, A, R, Q, N = (
    ReviewStatus.pending,
    ReviewStatus.approved,
    ReviewStatus.rejected,
    ReviewStatus.quarantined,
    None,
)
APPROVE, REJECT, QUARANTINE, RELEASE = (
    ReviewTransitionAction.approve,
    ReviewTransitionAction.reject,
    ReviewTransitionAction.quarantine,
    ReviewTransitionAction.release,
)

#: (현재 상태, 액션) → 도착 상태 또는 None(불허). 20칸 전수 — 허용 4.
_EXPECTED: list[tuple[ReviewStatus | None, ReviewTransitionAction, ReviewStatus | None]] = [
    # approve
    (P, APPROVE, A),
    (A, APPROVE, None),
    (R, APPROVE, None),
    (Q, APPROVE, None),
    (N, APPROVE, None),
    # reject
    (P, REJECT, R),
    (A, REJECT, None),
    (R, REJECT, None),
    (Q, REJECT, None),
    (N, REJECT, None),
    # quarantine
    (P, QUARANTINE, None),
    (A, QUARANTINE, Q),
    (R, QUARANTINE, None),
    (Q, QUARANTINE, None),
    (N, QUARANTINE, None),
    # release
    (P, RELEASE, None),
    (A, RELEASE, None),
    (R, RELEASE, None),
    (Q, RELEASE, A),
    (N, RELEASE, None),
]

#: 상태 → 허용 액션(열거 순서 approve·reject·quarantine·release). 5상태 전수.
_ALLOWED: list[tuple[ReviewStatus | None, tuple[ReviewTransitionAction, ...]]] = [
    (P, (APPROVE, REJECT)),
    (A, (QUARANTINE,)),
    (R, ()),
    (Q, (RELEASE,)),
    (N, ()),
]


def test_expected_table_shape_is_20_cells_with_4_allowed() -> None:
    """분모 단언 — 표가 줄어들면 '불허 16'이 공허하게 통과한다."""
    assert len(_EXPECTED) == 20
    assert sum(1 for *_, t in _EXPECTED if t is not None) == 4
    assert len({(c, a) for c, a, _ in _EXPECTED}) == 20


@pytest.mark.parametrize(("current", "action", "target"), _EXPECTED)
def test_transition_table_cell(
    current: ReviewStatus | None,
    action: ReviewTransitionAction,
    target: ReviewStatus | None,
) -> None:
    if target is None:
        with pytest.raises(IllegalReviewTransition) as info:
            resolve_review_transition(current, action)
        assert info.value.current is current
        assert info.value.action is action
        assert isinstance(info.value, ValueError)
    else:
        assert resolve_review_transition(current, action) is target


@pytest.mark.parametrize(("current", "expected"), _ALLOWED)
def test_allowed_actions_table(
    current: ReviewStatus | None, expected: tuple[ReviewTransitionAction, ...]
) -> None:
    assert allowed_actions(current) == expected


def test_allowed_actions_agree_with_resolve_for_every_cell() -> None:
    """표시용 목록과 실행 판정이 갈라지면 화면은 버튼을 보이는데 서버는 409다."""
    for current in (P, A, R, Q, N):
        for action in ReviewTransitionAction:
            try:
                resolve_review_transition(current, action)
                ok = True
            except IllegalReviewTransition:
                ok = False
            assert (action in allowed_actions(current)) is ok, (current, action)


def test_only_quarantine_requires_reason() -> None:
    assert action_requires_reason(QUARANTINE) is True
    assert action_requires_reason(APPROVE) is False
    assert action_requires_reason(REJECT) is False
    assert action_requires_reason(RELEASE) is False


def test_action_values_are_literal_and_fit_audit_column() -> None:
    """감사 `action` 컬럼 값과 같다 — 값 변경은 감사 이력 의미를 바꾼다. String(16) 이내."""
    assert [a.value for a in ReviewTransitionAction] == [
        "approve",
        "reject",
        "quarantine",
        "release",
    ]
    assert all(len(a.value) <= 16 for a in ReviewTransitionAction)


def test_audit_action_enum_carries_transition_values_and_keeps_crud() -> None:
    from whymath_backend.schema.enums import PrivacyAuditAction

    assert {a.value for a in PrivacyAuditAction} == {
        "create",
        "update",
        "delete",
        "approve",
        "reject",
        "quarantine",
        "release",
    }
    assert all(len(a.value) <= 16 for a in PrivacyAuditAction)
