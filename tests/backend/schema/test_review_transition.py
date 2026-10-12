"""검수 상태 전이 계약 동결 (ADMIN-07) — 기대표는 코드와 독립인 손으로 적은 리터럴이다.

기대값을 `_TRANSITIONS`에서 파생하면 표에 한 칸을 잘못 추가해도 테스트가 같이 따라가
통과한다(동어반복). 그래서 4 액션 × 5 상태 = 20칸을 **허용 4 · 불허 16**으로 직접 적는다.
`None`(미설정) 행이 전부 불허인 것이 "모른다 ≠ pending"의 동결이다.
"""

from __future__ import annotations

import pytest

from whymath_backend.schema.enums import ReviewStatus
from whymath_backend.schema.review_transition import (
    INITIAL_REVIEW_STATUSES,
    QUARANTINE_REASON_MAX_LENGTH,
    IllegalInitialReviewStatus,
    IllegalReviewStatusChange,
    IllegalReviewTransition,
    QuarantineReasonRequired,
    QuarantineRecordLocked,
    ReviewTransitionAction,
    action_for_status_change,
    action_requires_reason,
    allowed_actions,
    ensure_initial_review_status,
    plan_review_field_change,
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
        # P3-12 — CMS 버전 전이·롤백 감사(`api/admin_cms.py`가 전이 이름 그대로 기록한다)
        "submit",
        "request_changes",
        "pass_review",
        "fail_qa",
        "publish",
        "deprecate",
        "retire",
        "rollback",
    }
    assert all(len(a.value) <= 16 for a in PrivacyAuditAction)


# ── ADMIN-16: 목표 상태 → 액션 역해석 · PATCH 판정 ────────────────────────────────────

#: (현재, 목표) → 액션 또는 None(불허). 5 현재 × 4 목표 = 20칸 전수를 **손으로** 적는다 —
#: 정방향 표(`_EXPECTED`)에서 파생하면 역해석 버그가 정방향과 같이 움직여 통과한다.
_EXPECTED_REVERSE: list[tuple[ReviewStatus | None, ReviewStatus, ReviewTransitionAction | None]] = [
    (N, P, None),
    (N, A, None),
    (N, R, None),
    (N, Q, None),
    (P, P, None),
    (P, A, APPROVE),
    (P, R, REJECT),
    (P, Q, None),
    (A, P, None),
    (A, A, None),
    (A, R, None),
    (A, Q, QUARANTINE),
    (R, P, None),
    (R, A, None),
    (R, R, None),
    (R, Q, None),
    (Q, P, None),
    (Q, A, RELEASE),
    (Q, R, None),
    (Q, Q, None),
]


def _label(state: ReviewStatus | None) -> str:
    return "미설정" if state is None else state.value


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    _EXPECTED_REVERSE,
    ids=[f"{_label(c)}->{t.value}" for c, t, _ in _EXPECTED_REVERSE],
)
def test_reverse_lookup_matches_the_hand_written_table(
    current: ReviewStatus | None,
    target: ReviewStatus,
    expected: ReviewTransitionAction | None,
) -> None:
    if expected is None:
        with pytest.raises(IllegalReviewStatusChange) as info:
            action_for_status_change(current, target)
        assert info.value.current is current and info.value.target is target
        assert info.value.code == "illegal_transition"
    else:
        assert action_for_status_change(current, target) is expected


def test_reverse_lookup_has_exactly_four_hits_and_agrees_with_the_forward_table() -> None:
    """정방향과 역방향이 같은 표를 읽는다 — 역해석 결과를 정방향에 되먹이면 목표가 돌아와야 한다."""
    hits = [(c, t, a) for c, t, a in _EXPECTED_REVERSE if a is not None]
    assert len(hits) == 4
    for current, target, action in hits:
        assert current is not None
        assert resolve_review_transition(current, action) is target


def test_reverse_lookup_refuses_a_cleared_target() -> None:
    """목표가 NULL(상태 소거)인 변경은 어떤 액션에도 대응하지 않는다."""
    for current in (N, P, A, R, Q):
        with pytest.raises(IllegalReviewStatusChange):
            action_for_status_change(current, None)


def _plan(**over: object) -> object:
    kwargs: dict[str, object] = {
        "current_status": P,
        "target_status": A,
        "reason_in_request": None,
        "quarantine_record_changed": False,
    }
    kwargs.update(over)
    return plan_review_field_change(**kwargs)  # type: ignore[arg-type]


def test_plan_unchanged_status_is_not_a_transition_even_if_the_record_changed() -> None:
    """상태가 그대로면 전이가 아니다 — 격리 기록 단독 편집은 이 계약의 범위 밖(계약 §7)."""
    for state in (N, P, A, R, Q):
        plan = _plan(current_status=state, target_status=state, quarantine_record_changed=True)
        assert plan.action is None and plan.quarantine_reason is None  # type: ignore[attr-defined]


def test_plan_legal_non_quarantine_transitions_carry_the_action() -> None:
    assert _plan(current_status=P, target_status=A).action is APPROVE  # type: ignore[attr-defined]
    assert _plan(current_status=P, target_status=R).action is REJECT  # type: ignore[attr-defined]
    assert _plan(current_status=Q, target_status=A).action is RELEASE  # type: ignore[attr-defined]


def test_plan_quarantine_returns_the_stripped_reason() -> None:
    plan = _plan(
        current_status=A,
        target_status=Q,
        reason_in_request="  복수 정답  ",
        quarantine_record_changed=True,
    )
    assert plan.action is QUARANTINE  # type: ignore[attr-defined]
    assert plan.quarantine_reason == "복수 정답"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "reason",
    [None, "", "   ", "\n\t", "x" * (QUARANTINE_REASON_MAX_LENGTH + 1)],
    ids=["None", "빈문자열", "공백", "개행탭", "상한초과"],
)
def test_plan_quarantine_without_a_usable_reason_is_refused(reason: str | None) -> None:
    with pytest.raises(QuarantineReasonRequired) as info:
        _plan(current_status=A, target_status=Q, reason_in_request=reason)
    assert info.value.code == "reason_required"


def test_plan_quarantine_reason_at_the_limit_is_accepted() -> None:
    plan = _plan(
        current_status=A,
        target_status=Q,
        reason_in_request="x" * QUARANTINE_REASON_MAX_LENGTH,
    )
    assert len(plan.quarantine_reason or "") == QUARANTINE_REASON_MAX_LENGTH  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("current", "target"), [(P, A), (P, R), (Q, A)], ids=["approve", "reject", "release"]
)
def test_plan_non_quarantine_transition_cannot_change_the_record(
    current: ReviewStatus, target: ReviewStatus
) -> None:
    with pytest.raises(QuarantineRecordLocked) as info:
        _plan(current_status=current, target_status=target, quarantine_record_changed=True)
    assert info.value.code == "quarantine_record_immutable"


def test_plan_illegal_change_is_refused_before_the_reason_is_looked_at() -> None:
    """불허 전이는 사유가 있어도 불허다 — 사유 검사가 불허 판정을 가리지 않는다."""
    with pytest.raises(IllegalReviewStatusChange):
        _plan(current_status=P, target_status=Q, reason_in_request="충분한 사유")


def test_reason_limit_is_shared_with_the_transition_route_schema() -> None:
    """POST의 `reason` 상한과 PATCH의 상한이 한 상수다 — 두 표면의 계약이 갈라지지 않는다."""
    from whymath_backend.api.admin_bff import AdminReviewTransitionRequest

    metadata = AdminReviewTransitionRequest.model_fields["reason"].metadata
    assert any(getattr(m, "max_length", None) == QUARANTINE_REASON_MAX_LENGTH for m in metadata)


# ── ADMIN-19: 생성 시점의 초기 상태 ────────────────────────────────────────────────

#: 요청 상태 → 허용 여부. 5칸 전수를 손으로 적는다(허용 2 · 불허 3) — `INITIAL_REVIEW_STATUSES`에서
#: 파생하면 집합에 한 칸을 잘못 넣어도 테스트가 같이 따라가 통과한다(동어반복).
_INITIAL_EXPECTED: list[tuple[ReviewStatus | None, bool]] = [
    (N, True),
    (P, True),
    (A, False),
    (R, False),
    (Q, False),
]


def test_initial_expected_table_shape_is_5_cells_with_2_allowed() -> None:
    """픽스처 자체의 변별력 — 상태 5종 전부를 한 번씩 덮고 허용은 정확히 2칸."""
    assert len(_INITIAL_EXPECTED) == 5
    assert len({s for s, _ in _INITIAL_EXPECTED}) == 5
    assert sum(1 for _, ok in _INITIAL_EXPECTED if ok) == 2


@pytest.mark.parametrize(
    ("requested", "allowed"),
    _INITIAL_EXPECTED,
    ids=[("미설정" if s is None else s.value) for s, _ in _INITIAL_EXPECTED],
)
def test_initial_status_cell(requested: ReviewStatus | None, allowed: bool) -> None:
    if allowed:
        ensure_initial_review_status(requested)
    else:
        with pytest.raises(IllegalInitialReviewStatus) as excinfo:
            ensure_initial_review_status(requested)
        assert excinfo.value.requested is requested


def test_initial_statuses_constant_matches_the_hand_written_table() -> None:
    """상수와 손으로 적은 표가 같은 집합이다 — 어느 한쪽만 바뀌면 여기서 갈라진다."""
    assert INITIAL_REVIEW_STATUSES == {s for s, ok in _INITIAL_EXPECTED if ok}


def test_every_non_initial_status_is_reachable_only_through_the_transition_table() -> None:
    """생성이 막은 3상태는 전부 전이표의 도착 상태로 *도달 가능*하다 — 막은 것이 정책 공백이 아님.

    approved·rejected(pending에서 도착)·quarantined(approved에서 도착)가 모두 표의 도착점이라,
    생성을 막아도 검수가 이 상태들로 가는 길은 열려 있다.
    """
    non_initial = {ReviewStatus.approved, ReviewStatus.rejected, ReviewStatus.quarantined}
    reachable = {
        resolve_review_transition(src, action)
        for src in (P, A, R, Q)
        for action in allowed_actions(src)
    }
    assert non_initial <= reachable


def test_illegal_initial_error_code_is_a_literal_and_the_message_names_the_way_out() -> None:
    """응답 계약의 코드 문자열은 리터럴로 동결하고, 메시지는 허용 값과 정식 경로를 알려 준다."""
    assert IllegalInitialReviewStatus.code == "illegal_initial_status"
    message = str(IllegalInitialReviewStatus(A))
    assert "approved" in message
    assert "pending" in message
    assert "전이" in message
    assert "미설정" in str(IllegalInitialReviewStatus(None))
