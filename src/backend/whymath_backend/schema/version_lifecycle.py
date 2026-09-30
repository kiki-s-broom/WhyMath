"""버전 생명주기 전이표 — 데이터로 선언한 상태 머신 (EOS-50 ⑨ · P3-11).

설계 정본: `docs/architecture/44_eos_version_management.md` §7(Lifecycle)·§9(Publish Gate).
축 판정: `docs/reviews/eos50_publish_gate_axis_judgment_2026-09-29.md`.

**이 튜플 한 장이 "어느 상태에서 어느 전이가 허용되는가"의 유일한 정본이다.** 전이 실행
(`l3/publish_gate.py`)은 이 표를 조회만 하며, 도착 상태를 스스로 고르지 않는다. 그래서 새 상태·
전이를 더할 때 고칠 곳은 여기 한 곳이고, 실행 코드에 `if status == ...` 분기가 늘어나지 않는다.

EOS-49 상태 머신의 **확장**이지 사본이 아니다: 상태 어휘(`VersionStatus`)·전이 이름
(`TransitionAction`)·게이트 종류(`GateKind`)는 `schema/version_header.py`가 소유하고, 이 파일은
그 어휘를 조합한 규칙만 담는다. EOS-49가 DB 트리거로 막는 두 규칙(PUBLISHED payload 불변·
PUBLISHED→DRAFT 금지)과 이 표의 정합은 `tests/backend/schema/test_version_lifecycle.py`가 동결한다.

흐름(P3-11 ⑨): Draft → Review → QA → Approved → Published → Deprecated / Rollback

    DRAFT ─submit→ IN_REVIEW ─pass_review→ IN_QA ─approve[QA]→ APPROVED ─publish[PUBLISH]→ PUBLISHED
      ↑               │                        │                                            │
      └─request_changes┘                        └─fail_qa→ DRAFT               deprecate/supersede
                                                                                              ↓
                          RETIRED ←retire─ DEPRECATED ─restore[RESTORE]→ PUBLISHED        DEPRECATED
                             ↑
                             └──────────── rollback(PUBLISHED → RETIRED · 결함 판정)

`[게이트]`가 붙은 간선만 검증 파이프라인을 경유한다. PUBLISHED로 들어가는 간선은 **전부**
게이트가 붙어 있다(미승인 Publish가 구조적으로 불가능 — 테스트가 동결).
"""

from __future__ import annotations

from dataclasses import dataclass

from whymath_backend.schema.version_header import GateKind, TransitionAction, VersionStatus


@dataclass(frozen=True)
class LifecycleTransition:
    """전이표 1행 — (전이 이름, 출발 상태) → 도착 상태 + 게이트 + 거버넌스 기록."""

    action: TransitionAction
    source: VersionStatus
    target: VersionStatus
    gate: GateKind | None
    """이 전이를 검증 파이프라인에 강제 경유시키는 게이트(없으면 None)."""
    stamp: str | None
    """이 전이가 행위자를 기록하는 `VersionGovernance` 필드명(없으면 None)."""
    compound_only: bool
    """True면 `apply_transition`으로 직접 부를 수 없다 — 발행·롤백 복합 연산의 부분이다."""
    description: str


_S = VersionStatus
_A = TransitionAction

LIFECYCLE_TRANSITIONS: tuple[LifecycleTransition, ...] = (
    LifecycleTransition(_A.SUBMIT, _S.DRAFT, _S.IN_REVIEW, None, None, False, "검토 제출"),
    LifecycleTransition(
        _A.REQUEST_CHANGES, _S.IN_REVIEW, _S.DRAFT, None, None, False, "검토 반려 — 초안 복귀"
    ),
    LifecycleTransition(
        _A.PASS_REVIEW, _S.IN_REVIEW, _S.IN_QA, None, "reviewed_by", False, "사람 검토 통과"
    ),
    LifecycleTransition(_A.FAIL_QA, _S.IN_QA, _S.DRAFT, None, None, False, "QA 불합격 — 초안 복귀"),
    LifecycleTransition(
        _A.APPROVE, _S.IN_QA, _S.APPROVED, GateKind.QA, "approved_by", False, "QA 게이트 + 승인"
    ),
    LifecycleTransition(
        _A.PUBLISH, _S.APPROVED, _S.PUBLISHED, GateKind.PUBLISH, None, False, "발행 게이트 + 발행"
    ),
    LifecycleTransition(
        _A.DEPRECATE, _S.PUBLISHED, _S.DEPRECATED, None, None, False, "발행본 폐기 예정"
    ),
    LifecycleTransition(_A.RETIRE, _S.DEPRECATED, _S.RETIRED, None, None, False, "은퇴(서빙 종료)"),
    LifecycleTransition(
        _A.SUPERSEDE, _S.PUBLISHED, _S.DEPRECATED, None, None, True, "새 판 발행으로 대체됨"
    ),
    # 롤백으로 내린 판은 결함 판정이다 — DEPRECATED(복원 후보)가 아니라 RETIRED로 보낸다.
    # DEPRECATED로 두면 다음 롤백이 방금 내린 결함 판을 "직전 발행본"으로 되살린다.
    LifecycleTransition(
        _A.ROLLBACK, _S.PUBLISHED, _S.RETIRED, None, None, True, "롤백 — 현재 발행본 은퇴(결함)"
    ),
    LifecycleTransition(
        _A.RESTORE,
        _S.DEPRECATED,
        _S.PUBLISHED,
        GateKind.RESTORE,
        None,
        True,
        "롤백 — 직전 발행본 복원(해시 재검증)",
    ),
)


class UndefinedTransitionError(ValueError):
    """전이표에 (전이 이름, 출발 상태) 쌍이 없다 — 미정의 전이는 거부한다(⑩)."""


class CompoundOnlyTransitionError(UndefinedTransitionError):
    """복합 연산 전용 전이를 단독으로 요청했다(supersede·rollback·restore)."""


def _build_index() -> dict[tuple[TransitionAction, VersionStatus], LifecycleTransition]:
    """(전이, 출발) → 행 색인. 같은 키가 두 번 나오면 표가 모호하므로 import 시점에 실패한다."""
    index: dict[tuple[TransitionAction, VersionStatus], LifecycleTransition] = {}
    for row in LIFECYCLE_TRANSITIONS:
        key = (row.action, row.source)
        if key in index:
            raise RuntimeError(f"전이표 중복 키: {row.action.value} from {row.source.value}")
        index[key] = row
    return index


_INDEX = _build_index()


def resolve_transition(
    action: TransitionAction | str,
    source: VersionStatus | str,
    *,
    allow_compound: bool = False,
) -> LifecycleTransition:
    """전이표에서 1행을 찾는다 — 없으면 `UndefinedTransitionError`.

    `allow_compound=False`(기본)에서 복합 전용 행을 만나면 `CompoundOnlyTransitionError`.
    문자열 입력은 어휘로 변환하며, 어휘에 없는 문자열도 미정의 전이로 거부한다.
    """
    try:
        action_v = TransitionAction(action)
        source_v = VersionStatus(source)
    except ValueError as exc:
        raise UndefinedTransitionError(
            f"어휘에 없는 전이 요청: action={action!r} source={source!r}"
        ) from exc
    row = _INDEX.get((action_v, source_v))
    if row is None:
        raise UndefinedTransitionError(
            f"미정의 전이: {action_v.value} from {source_v.value} "
            f"(허용: {[a.value for a in allowed_actions(source_v)]})"
        )
    if row.compound_only and not allow_compound:
        raise CompoundOnlyTransitionError(
            f"복합 연산 전용 전이 {action_v.value}는 단독 호출할 수 없다 "
            "(publish·rollback 연산을 사용하라)"
        )
    return row


def allowed_actions(
    source: VersionStatus | str, *, include_compound: bool = False
) -> tuple[TransitionAction, ...]:
    """출발 상태에서 허용된 전이 이름 — 표에서 파생한다(UI·오류 메시지용)."""
    source_v = VersionStatus(source)
    return tuple(
        row.action
        for row in LIFECYCLE_TRANSITIONS
        if row.source is source_v and (include_compound or not row.compound_only)
    )


__all__ = [
    "LifecycleTransition",
    "LIFECYCLE_TRANSITIONS",
    "UndefinedTransitionError",
    "CompoundOnlyTransitionError",
    "resolve_transition",
    "allowed_actions",
]
