"""버전 생명주기 전이표 동결 — EOS-50 ⑨⑩ (P3-11).

전이표(`schema/version_lifecycle.py`의 `LIFECYCLE_TRANSITIONS`)가 상태 머신의 유일한 정본인지,
그리고 그 표가 구조적으로 "미승인 Publish"를 허용하지 않는지를 동결한다.

- 구조 불변식(표가 바뀌어도 성립해야 하는 것): PUBLISHED로 들어가는 간선은 전부 게이트가 붙는다 ·
  PUBLISHED→DRAFT 간선이 없다(EOS-49 DB 트리거와 정합) · RETIRED는 종착 · 모든 상태가 DRAFT에서
  도달 가능 · 게이트 간선의 거버넌스 기록 필드는 실재한다.
- 변경 감지 동결: 간선 집합 스냅숏. 표를 바꾸는 PR은 이 스냅숏도 함께 바꿔야 한다(의도적 변경을
  리뷰에 드러나게 — 이 스냅숏은 코드가 읽는 사본이 아니라 비교 기준이다).
- 미정의 전이 RED: 표에 없는 (전이, 출발) 쌍·어휘 밖 문자열·복합 전용 전이의 단독 호출은 전부 예외.
"""

from __future__ import annotations

from collections import deque

import pytest

from whymath_backend.schema.version_header import (
    GateKind,
    TransitionAction,
    VersionGovernance,
    VersionStatus,
)
from whymath_backend.schema.version_lifecycle import (
    LIFECYCLE_TRANSITIONS,
    CompoundOnlyTransitionError,
    LifecycleTransition,
    UndefinedTransitionError,
    allowed_actions,
    resolve_transition,
)

_S = VersionStatus
_A = TransitionAction

# 변경 감지 스냅숏 — (전이, 출발, 도착, 게이트, 복합전용).
_EXPECTED_EDGES = {
    (_A.SUBMIT, _S.DRAFT, _S.IN_REVIEW, None, False),
    (_A.REQUEST_CHANGES, _S.IN_REVIEW, _S.DRAFT, None, False),
    (_A.PASS_REVIEW, _S.IN_REVIEW, _S.IN_QA, None, False),
    (_A.FAIL_QA, _S.IN_QA, _S.DRAFT, None, False),
    (_A.APPROVE, _S.IN_QA, _S.APPROVED, GateKind.QA, False),
    (_A.PUBLISH, _S.APPROVED, _S.PUBLISHED, GateKind.PUBLISH, False),
    (_A.DEPRECATE, _S.PUBLISHED, _S.DEPRECATED, None, False),
    (_A.RETIRE, _S.DEPRECATED, _S.RETIRED, None, False),
    (_A.SUPERSEDE, _S.PUBLISHED, _S.DEPRECATED, None, True),
    (_A.ROLLBACK, _S.PUBLISHED, _S.RETIRED, None, True),
    (_A.RESTORE, _S.DEPRECATED, _S.PUBLISHED, GateKind.RESTORE, True),
}


def _edges() -> set[tuple[object, ...]]:
    return {(t.action, t.source, t.target, t.gate, t.compound_only) for t in LIFECYCLE_TRANSITIONS}


def test_transition_table_matches_the_frozen_snapshot() -> None:
    """전이표의 간선 집합이 스냅숏과 정확히 같다(추가·삭제 양방향)."""
    assert _edges() == _EXPECTED_EDGES


def test_every_edge_into_published_is_gated() -> None:
    """⑩ 미승인 Publish 구조 차단 — PUBLISHED로 들어가는 간선은 전부 게이트가 붙는다."""
    into_published = [t for t in LIFECYCLE_TRANSITIONS if t.target is _S.PUBLISHED]
    assert into_published, "PUBLISHED로 들어가는 간선이 0건 — 스캔 대상이 없는 가드는 공허하다"
    ungated = [t.action.value for t in into_published if t.gate is None]
    assert not ungated, f"게이트 없이 PUBLISHED로 들어가는 간선: {ungated}"


def test_publish_gate_only_reachable_from_approved() -> None:
    """직접 호출 가능한 PUBLISHED 진입은 APPROVED에서만 — 승인 없이 발행하는 경로가 없다."""
    direct = [
        t.source for t in LIFECYCLE_TRANSITIONS if t.target is _S.PUBLISHED and not t.compound_only
    ]
    assert direct == [_S.APPROVED]


def test_no_edge_back_to_draft_from_published() -> None:
    """EOS-49 DB 트리거가 막는 PUBLISHED→DRAFT를 표도 선언하지 않는다(두 방어선 정합)."""
    assert not [
        t for t in LIFECYCLE_TRANSITIONS if t.source is _S.PUBLISHED and t.target is _S.DRAFT
    ]


def test_retired_is_terminal() -> None:
    assert not [t for t in LIFECYCLE_TRANSITIONS if t.source is _S.RETIRED]


def test_every_status_is_reachable_from_draft() -> None:
    """어휘에 있는데 표로 도달할 수 없는 상태 = 죽은 상태(표·어휘 불일치)."""
    seen = {_S.DRAFT}
    queue: deque[VersionStatus] = deque([_S.DRAFT])
    while queue:
        cur = queue.popleft()
        for t in LIFECYCLE_TRANSITIONS:
            if t.source is cur and t.target not in seen:
                seen.add(t.target)
                queue.append(t.target)
    assert seen == set(VersionStatus)


def test_every_action_is_used() -> None:
    """어휘에 있는데 표에 없는 전이 이름 = 어휘·표 불일치."""
    assert {t.action for t in LIFECYCLE_TRANSITIONS} == set(TransitionAction)


def test_stamp_fields_exist_on_governance() -> None:
    fields = set(VersionGovernance.model_fields)
    for t in LIFECYCLE_TRANSITIONS:
        if t.stamp is not None:
            assert t.stamp in fields, f"{t.action.value}: 없는 거버넌스 필드 {t.stamp!r}"


def test_approval_stamp_is_on_the_qa_gated_edge() -> None:
    """승인자 기록은 QA 게이트 간선과 같은 간선이다 — 게이트 없이 승인자가 생기지 않는다."""
    stamped = [t for t in LIFECYCLE_TRANSITIONS if t.stamp == "approved_by"]
    assert len(stamped) == 1 and stamped[0].gate is GateKind.QA


@pytest.mark.parametrize("row", LIFECYCLE_TRANSITIONS, ids=lambda r: r.action.value)
def test_resolve_returns_the_declared_row(row: LifecycleTransition) -> None:
    assert resolve_transition(row.action, row.source, allow_compound=True) is row


def test_resolve_accepts_string_vocabulary() -> None:
    assert resolve_transition("publish", "APPROVED").target is _S.PUBLISHED


@pytest.mark.parametrize(
    ("action", "source"),
    [
        (_A.PUBLISH, _S.DRAFT),  # 미승인 Publish
        (_A.PUBLISH, _S.IN_REVIEW),
        (_A.PUBLISH, _S.IN_QA),
        (_A.PUBLISH, _S.PUBLISHED),
        (_A.APPROVE, _S.IN_REVIEW),  # QA 건너뛴 승인
        (_A.SUBMIT, _S.PUBLISHED),
        (_A.RETIRE, _S.PUBLISHED),
        (_A.DEPRECATE, _S.RETIRED),
    ],
)
def test_undefined_transitions_are_red(action: TransitionAction, source: VersionStatus) -> None:
    """⑩ 미정의 전이는 예외 — 조용히 무시하거나 가까운 전이로 대체하지 않는다."""
    with pytest.raises(UndefinedTransitionError):
        resolve_transition(action, source)


@pytest.mark.parametrize(("action", "source"), [("publish", "BOGUS"), ("teleport", "DRAFT")])
def test_out_of_vocabulary_is_red(action: str, source: str) -> None:
    with pytest.raises(UndefinedTransitionError):
        resolve_transition(action, source)


@pytest.mark.parametrize(
    ("action", "source"),
    [(_A.SUPERSEDE, _S.PUBLISHED), (_A.ROLLBACK, _S.PUBLISHED), (_A.RESTORE, _S.DEPRECATED)],
)
def test_compound_only_transitions_refuse_direct_calls(
    action: TransitionAction, source: VersionStatus
) -> None:
    with pytest.raises(CompoundOnlyTransitionError):
        resolve_transition(action, source)
    assert resolve_transition(action, source, allow_compound=True).action is action


def test_allowed_actions_is_derived_from_the_table() -> None:
    assert allowed_actions(_S.PUBLISHED) == (_A.DEPRECATE,)
    assert set(allowed_actions(_S.PUBLISHED, include_compound=True)) == {
        _A.DEPRECATE,
        _A.SUPERSEDE,
        _A.ROLLBACK,
    }
    assert allowed_actions(_S.RETIRED) == ()
