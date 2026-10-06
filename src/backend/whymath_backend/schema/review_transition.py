"""검수 상태 전이 계약 — 어떤 `review_status` 전이가 허용되는가(ADMIN-07).

**순수 함수·불변 상수만 둔다**(DB·HTTP·시계 의존 0). 전이 *규칙*의 단일 권위가 여기라서
`api`(L5)는 이 모듈을 호출만 하고 규칙을 재구현하지 않으며, 웹 화면도 규칙을 복제하지 않고
서버가 내려 주는 `allowed_actions(...)`를 그대로 그린다(표현 ≠ 의미).

전이표(그 외 전부 불허):

    approve    : pending     -> approved
    reject     : pending     -> rejected
    quarantine : approved    -> quarantined
    release    : quarantined -> approved

**현재 상태 `None`(미설정)은 어떤 액션도 불허한다** — "모른다 ≠ pending". `review_status`가
NULL인 문항은 *아직 검수 큐에 들어오지 않은* 것이지 *검수 대기*가 아니다. 3상태(알려진 값/
미설정)를 `pending`으로 접으면 판정된 적 없는 문항이 승인 경로로 흘러든다.

`rejected -> *`는 의도적으로 막혀 있다(되살리려면 문항을 고쳐 새로 적재하는 경로가 맞다).
격리 해제(`release`)는 `approved`로만 돌아가며 사유·시각은 지우지 않는다(격리 계약 §5-2) —
그 *기록 규칙*은 전이 규칙이 아니라 집행 지점(`api/admin_bff.py`)의 책임이다.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from whymath_backend.schema.enums import ReviewStatus


class ReviewTransitionAction(StrEnum):
    """검수 상태를 바꾸는 운영자 액션 4종. 값은 감사 `action` 컬럼 값과 같다(≤16자)."""

    approve = "approve"
    reject = "reject"
    quarantine = "quarantine"
    release = "release"


class IllegalReviewTransition(ValueError):
    """전이표에 없는 `(현재 상태, 액션)` 조합."""

    def __init__(self, current: ReviewStatus | None, action: ReviewTransitionAction) -> None:
        self.current = current
        self.action = action
        shown = current.value if current is not None else "미설정"
        super().__init__(f"허용되지 않는 검수 전이: 현재 상태 {shown} 에서 {action.value}")


#: 액션 → (출발 상태, 도착 상태). 읽기 전용 매핑 — 호출 측이 규칙을 바꿀 수 없다.
_TRANSITIONS: MappingProxyType[ReviewTransitionAction, tuple[ReviewStatus, ReviewStatus]] = (
    MappingProxyType(
        {
            ReviewTransitionAction.approve: (ReviewStatus.pending, ReviewStatus.approved),
            ReviewTransitionAction.reject: (ReviewStatus.pending, ReviewStatus.rejected),
            ReviewTransitionAction.quarantine: (ReviewStatus.approved, ReviewStatus.quarantined),
            ReviewTransitionAction.release: (ReviewStatus.quarantined, ReviewStatus.approved),
        }
    )
)

#: 사유(`reason`)를 반드시 요구하는 액션 — 격리 계약 §3(격리 사유 기록 의무).
_REASON_REQUIRED: frozenset[ReviewTransitionAction] = frozenset({ReviewTransitionAction.quarantine})


def resolve_review_transition(
    current: ReviewStatus | None, action: ReviewTransitionAction
) -> ReviewStatus:
    """`current`에서 `action`을 적용한 도착 상태. 불허면 `IllegalReviewTransition`."""
    if current is None:
        raise IllegalReviewTransition(current, action)
    source, target = _TRANSITIONS[action]
    if current is not source:
        raise IllegalReviewTransition(current, action)
    return target


def allowed_actions(current: ReviewStatus | None) -> tuple[ReviewTransitionAction, ...]:
    """`current`에서 허용되는 액션(표시용). 열거 순서는 `ReviewTransitionAction` 정의 순서."""
    if current is None:
        return ()
    return tuple(a for a in ReviewTransitionAction if _TRANSITIONS[a][0] is current)


def action_requires_reason(action: ReviewTransitionAction) -> bool:
    """이 액션이 사유를 필수로 요구하는가(quarantine만 True)."""
    return action in _REASON_REQUIRED
