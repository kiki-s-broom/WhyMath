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

**집행 지점은 둘이다(ADMIN-16)**: 검수 상태를 쓰는 관리자 표면은 `POST /v1/admin/review-queue/
items/{id}/transitions`(액션을 직접 받는다)와 `PATCH /v1/problems/{id}`(목표 상태를 받는다) 둘이며,
후자는 `action_for_status_change`로 *목표 상태를 액션으로 역해석*해 같은 표를 거친다. 표를 두 벌
만들지 않기 위해 역해석도 이 표를 읽는 공개 함수(`allowed_actions`·`resolve_review_transition`)만
쓴다. PATCH 쪽 판정(`plan_review_field_change`)도 순수 함수로 여기에 둔다 — 라우터는 HTTP 번역만
한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from whymath_backend.schema.enums import ReviewStatus

#: 격리 사유 최대 길이 — `POST …/transitions`의 `reason`과 `PATCH`의 `quarantine_reason`이 같은
#: 상한을 쓴다(두 표면의 계약이 갈라지면 한쪽으로만 긴 사유가 들어간다).
QUARANTINE_REASON_MAX_LENGTH = 2000


class ReviewTransitionAction(StrEnum):
    """검수 상태를 바꾸는 운영자 액션 4종. 값은 감사 `action` 컬럼 값과 같다(≤16자)."""

    approve = "approve"
    reject = "reject"
    quarantine = "quarantine"
    release = "release"


class IllegalReviewTransition(ValueError):  # noqa: N818 — 계약상 이름(Error 접미사 없음)
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


#: 인간 *판정*(검수 타이머 `finished` 이벤트를 남겨야 하는) 액션 — approve·reject뿐(ADMIN-18).
#: `ReviewVerdict`(approved|approved_with_edit|rejected)에 대응 값이 있는 액션이 이것이다.
#: quarantine·release는 **사후 회수·복원**이지 새 검수 판정이 아니므로(ReviewVerdict에 값이 없고
#: HIT는 "검수 한 건에 든 인간 시간"을 재는 지표다) 타이머 세션을 요구하지 않는다.
_TIMER_VERDICT: MappingProxyType[ReviewTransitionAction, Literal["approved", "rejected"]] = (
    MappingProxyType(
        {
            ReviewTransitionAction.approve: "approved",
            ReviewTransitionAction.reject: "rejected",
        }
    )
)

#: 반려코드(GenerationFailureCode F1~F8)를 반드시 요구하는 액션 — 설계서 §4 "모든 검수 반려는 8코드
#: 중 하나로 강제 분류". 함수 레벨 집행(`schema/review_timer.py`)을 HTTP 경계에서도 건다.
_FAILURE_CODE_REQUIRED: frozenset[ReviewTransitionAction] = frozenset(
    {ReviewTransitionAction.reject}
)


def verdict_for_action(action: ReviewTransitionAction) -> Literal["approved", "rejected"] | None:
    """이 액션이 낳는 검수 판정(타이머 이벤트 `verdict`). 판정이 아닌 액션이면 None."""
    return _TIMER_VERDICT.get(action)


def action_requires_review_session(action: ReviewTransitionAction) -> bool:
    """이 액션이 검수 세션(타이머)을 필수로 요구하는가(approve·reject만 True) — ADMIN-18."""
    return action in _TIMER_VERDICT


def action_requires_failure_code(action: ReviewTransitionAction) -> bool:
    """이 액션이 반려코드(F1~F8)를 필수로 요구하는가(reject만 True) — ADMIN-18."""
    return action in _FAILURE_CODE_REQUIRED


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


# ──────────────────────────────────────────────────────────────────────────
# ADMIN-16 — 목표 상태로 들어오는 표면(PATCH)이 같은 표를 거치게 하는 역해석·판정
# ──────────────────────────────────────────────────────────────────────────


class IllegalReviewStatusChange(ValueError):  # noqa: N818 — 계약상 이름(Error 접미사 없음)
    """`(현재 상태, 목표 상태)` 쌍에 대응하는 전이 액션이 표에 없다.

    `IllegalReviewTransition`이 *액션을 이미 아는* 표면(POST)의 거부라면, 이쪽은 *목표 상태만 아는*
    표면(PATCH)의 거부다 — 액션을 특정할 수 없으므로 액션 대신 목표를 싣는다.
    """

    code = "illegal_transition"

    def __init__(self, current: ReviewStatus | None, target: ReviewStatus | None) -> None:
        self.current = current
        self.target = target
        shown_current = current.value if current is not None else "미설정"
        shown_target = target.value if target is not None else "미설정"
        super().__init__(f"허용되지 않는 검수 상태 변경: {shown_current} → {shown_target}")


class QuarantineReasonRequired(ValueError):  # noqa: N818 — 계약상 이름(Error 접미사 없음)
    """격리 전이에 *이번 요청의* 사유가 없다(공백뿐이거나 상한 초과 포함)."""

    code = "reason_required"


class QuarantineRecordLocked(ValueError):  # noqa: N818 — 계약상 이름(Error 접미사 없음)
    """격리 전이가 아닌 상태 변경이 격리 기록(사유·시각)을 함께 바꾸려 했다.

    격리 계약 §5-2 — 회수 이력은 해제 후에도 영구 기록이다. approve/reject/release가 이 기록을
    지우거나 덮어쓰면 "전에도 같은 이유로 회수됐다"는 근거가 사라진다.
    """

    code = "quarantine_record_immutable"


class VerdictRequiresReviewSession(ValueError):  # noqa: N818 — 계약상 이름(Error 접미사 없음)
    """목표 상태로 들어오는 표면(PATCH)이 인간 판정(approve·reject) 전이를 요구했다(ADMIN-18).

    PATCH는 반려코드·검수 세션(타이머)을 실을 자리가 없다. 그대로 통과시키면 "반려코드 없는 반려",
    "타이머 없는 판정"이 이 표면으로 새므로 거부하고 `POST …/transitions`로 안내한다.
    """

    code = "review_session_required"

    def __init__(self, action: ReviewTransitionAction) -> None:
        self.action = action
        super().__init__(
            f"{action.value} 판정은 반려코드·검수 세션(타이머)이 필요해 이 표면으로는 불가합니다. "
            "POST /v1/admin/review-queue/items/{problem_id}/transitions 를 사용하세요."
        )


def action_for_status_change(
    current: ReviewStatus | None, target: ReviewStatus | None
) -> ReviewTransitionAction:
    """`current → target`에 대응하는 전이 액션(표의 **역조회**).

    표에 없으면 `IllegalReviewStatusChange`다. 역조회가 유일한 것은 표가 `(출발, 도착)` 쌍을
    액션마다 하나씩 갖기 때문이다(approve와 release는 도착이 같지만 출발이 다르다).
    `current is None`(미설정)이면 `allowed_actions`가 비어 항상 거부된다 — "모른다 ≠ pending"을
    PATCH 경로에서도 지킨다. 표는 `allowed_actions`·`resolve_review_transition`으로만 읽는다
    (두 번째 표를 만들지 않는다).
    """
    if current is not None and target is not None:
        for action in allowed_actions(current):
            if resolve_review_transition(current, action) is target:
                return action
    raise IllegalReviewStatusChange(current, target)


@dataclass(frozen=True, slots=True)
class ReviewFieldChangePlan:
    """PATCH가 검수 소관 필드(상태·격리 기록)를 건드렸을 때의 판정 결과.

    `action is None`이면 검수 상태가 바뀌지 않은 요청이다(전이가 아님). 그 경우 감사 행의 동작은
    기존 그대로 `update`이고, 격리 기록 필드의 단독 편집은 이 계약의 범위 밖이다(계약 §7).
    """

    action: ReviewTransitionAction | None
    #: 격리 전이에서 기록할 (공백 제거된) 사유. 격리 전이가 아니면 None.
    quarantine_reason: str | None = None


def plan_review_field_change(
    *,
    current_status: ReviewStatus | None,
    target_status: ReviewStatus | None,
    reason_in_request: str | None,
    quarantine_record_changed: bool,
) -> ReviewFieldChangePlan:
    """PATCH의 검수 상태 변경이 허용되는지 판정한다(순수 — DB·HTTP·시계 의존 0).

    Args:
      current_status: DB의 *현재* 상태(행 잠금 뒤 재조회한 값).
      target_status: 병합 결과가 요구하는 상태.
      reason_in_request: **요청 본문이 직접 보낸** `quarantine_reason`(없으면 None). 병합 결과가
        아니라 본문 값이어야 한다 — 병합 결과를 쓰면 과거 격리의 낡은 사유가 새 격리에 조용히
        재사용된다(POST 경로는 매 격리마다 새 사유를 요구한다).
      quarantine_record_changed: 병합 결과가 격리 기록(사유 또는 시각)을 현재 값과 다르게 만드는가.

    Raises:
      IllegalReviewStatusChange: 표에 없는 상태 변경(rejected→approved · 미설정→무엇이든 등).
      QuarantineReasonRequired: 격리 전이인데 이번 요청의 사유가 비었거나 상한을 넘는다.
      QuarantineRecordLocked: 격리 전이가 아닌 상태 변경이 격리 기록을 함께 바꿨다.
    """
    if current_status is target_status:
        return ReviewFieldChangePlan(action=None)
    action = action_for_status_change(current_status, target_status)
    if action_requires_reason(action):
        reason = (reason_in_request or "").strip()
        if not reason or len(reason) > QUARANTINE_REASON_MAX_LENGTH:
            raise QuarantineReasonRequired(
                f"격리 전이는 이번 요청의 사유(quarantine_reason)가 필요합니다"
                f"(공백 제외 1자 이상, {QUARANTINE_REASON_MAX_LENGTH}자 이하)."
            )
        return ReviewFieldChangePlan(action=action, quarantine_reason=reason)
    if quarantine_record_changed:
        raise QuarantineRecordLocked(
            "격리 기록(quarantine_reason·quarantined_at)은 격리 전이에서만 기록되며 "
            f"{action.value} 전이와 함께 바꿀 수 없습니다."
        )
    return ReviewFieldChangePlan(action=action)
