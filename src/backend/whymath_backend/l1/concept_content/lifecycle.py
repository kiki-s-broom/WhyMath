"""개념 생애 상태 — 학생 공개 관문 술어 + 상태 전환 함수 (PED-17 A1).

이 모듈은 두 가지를 소유한다.

① `is_student_visible` — 학생 경로(`l4/content_supply.py::resolve_concept_content`)가 개념 행을 열지
   말지 정하는 **단일 술어**. 어휘·전환표는 `schema/concept_lifecycle.py`가 정본이다.
② `transition_concept_state` — `concept_content.lifecycle_status`를 바꾸는 **유일한 코드**.

────────────────────────────────────────────────────────────────────────────
왜 `review_status`와 별개 축인가 (그리고 왜 둘 다 보는가)
────────────────────────────────────────────────────────────────────────────
`review_status`(ai_estimated·reviewed·rejected)는 *사람 검수 라벨*이다. C안은 사람 검수 없이 AI가
만들고 자동 검증을 통과한 개념도 학생에게 열므로, 공개 근거가 `reviewed`일 수 없다. 그래서 *학생
공개
생애*를 별도 컬럼으로 둔다. 그러나 출처가 '사람 검수'인 행은 `review_status == reviewed`도 함께
요구한다 — 코퍼스 재적재가 `review_status`를 `ai_estimated`로 되돌리는 경로(CONT-05 ③)가 이미 있고,
생애 컬럼만 보면 그 강등이 학생에게 닿지 않기 때문이다(fail-open). 즉 **더 엄격한 쪽이 이긴다**.

────────────────────────────────────────────────────────────────────────────
전환 함수의 계약
────────────────────────────────────────────────────────────────────────────
- 허용 전환은 5쌍뿐이고 각 쌍은 호출 가능한 *경로*(`ConceptTransitionVia`)가 정해져 있다. 쌍도 맞고
  경로도 맞아야 통과한다. 그 외는 **쓰기 전에** 거부하고 오류 로그를 남긴 뒤 예외를 던진다.
- 상태 변경과 기록 행(`concept_state_transition`)은 **같은 트랜잭션**에 들어간다. 이 함수는 커밋하지
  않는다(호출자가 커밋) — 기록 없이 상태만 바뀌거나 그 반대가 되는 중간 상태가 없다.
- 긴급 정지 경로는 `kiki`만 쓸 수 있다. **한계(명시)**: 호출자가 `changed_by_kind`를 스스로
  신고하므로
  이 함수는 *실수*와 *에이전트의 오용*을 막을 뿐 *위조*를 막지 못한다. 위조 방어는 호출 지점(누가
  이 함수를 부르는가)의 코드 리뷰와 AST 거버넌스 테스트가 맡는다.
- 이 함수는 경로가 *실제로 그 작업의 합격 판정을 거쳤는지*는 검증하지 못한다(B6이 통과했는지는
  B6의 소관). 경로는 호출자의 선언이며, 기록 테이블이 그 선언을 사후 감사 가능하게 남긴다.

계층: L1. 의존은 `db/models`·`schema`뿐이다(역방향 의존 없음).
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.concept_content import ConceptContent
from whymath_backend.db.models.concept_lifecycle_log import ConceptStateTransition
from whymath_backend.l1.concept_content.review_gate import is_supply_eligible
from whymath_backend.schema.concept_lifecycle import (
    ALLOWED_TRANSITIONS,
    KIKI_ONLY_VIA,
    ChangedByKind,
    ConceptContentOrigin,
    ConceptLifecycleState,
    ConceptTransitionVia,
)

logger = logging.getLogger("whymath.l1.concept_content.lifecycle")

# 사람이 거부한 라벨. 학생 공개 술어가 AI 생성 행에서도 이 값을 막는다.
_REJECTED_STATUS = "rejected"


class ConceptTransitionError(Exception):
    """상태 전환 거부의 공통 부모 — 호출자는 이 타입 하나로 거부 전체를 잡을 수 있다."""


class InvalidConceptTransitionError(ConceptTransitionError):
    """허용되지 않은 전환 — 전환표에 없는 쌍, 쌍에 맞지 않는 경로, 권한 없는 주체, 빈 사유."""


class ConceptNotFoundError(ConceptTransitionError):
    """전환 대상 개념 행이 없다 — 조용히 넘기지 않고 거부한다(없는 행의 기록을 남기지 않는다)."""


def is_student_visible(
    *,
    lifecycle_status: str | None,
    content_origin: str | None,
    review_status: str | None,
) -> bool:
    """학생에게 보여 줄 수 있는 개념 행인가 — **학생 경로의 유일한 관문 술어**.

    규칙(더 엄격한 쪽이 이긴다):
      ① `lifecycle_status`가 '공개됨'이 아니면 거부. 초안·검증됨·회수됨·None·표기 변형은 전부 거부.
      ② 출처 '사람 검수'면 `review_status == reviewed`도 유지돼야 한다(재적재 강등 즉시 차단).
      ③ 출처 'AI 생성'이면 사람이 `rejected`로 판정한 행은 막는다(사람의 거부가 AI 경로로 뒤집히지
        않는다).
      ④ 출처가 None이거나 어휘 밖이면 거부(모른다 ≠ 맞다).

    정규화하지 않는다. 표기 변형을 관대하게 받으면 관문이 변형에서 뚫린다(`is_supply_eligible`과
    같은
    이유). 순수 함수이며 raise하지 않는다.
    """
    if lifecycle_status != ConceptLifecycleState.PUBLISHED.value:
        return False
    if content_origin == ConceptContentOrigin.HUMAN_REVIEWED.value:
        return is_supply_eligible(review_status)
    if content_origin == ConceptContentOrigin.AI_GENERATED.value:
        return review_status != _REJECTED_STATUS
    return False


def row_is_student_visible(row: ConceptContent) -> bool:
    """`is_student_visible`의 행 어댑터 — 호출부가 세 컬럼을 풀어 쓰다 하나를 빠뜨리지 않게 한다."""
    return is_student_visible(
        lifecycle_status=row.lifecycle_status,
        content_origin=row.content_origin,
        review_status=row.review_status,
    )


def _reject(
    message: str,
    *,
    concept_code: str,
    from_state: str | None,
    to_state: str,
    via: str,
    changed_by_kind: str,
) -> InvalidConceptTransitionError:
    """거부 사유를 ERROR 로그로 남기고 예외를 만든다. 학생 식별 정보는 이 함수에 들어오지 않는다."""
    logger.error(
        "개념 상태 전환 거부 — concept=%s from=%s to=%s via=%s by_kind=%s: %s",
        concept_code,
        from_state,
        to_state,
        via,
        changed_by_kind,
        message,
    )
    return InvalidConceptTransitionError(message)


async def transition_concept_state(
    session: AsyncSession,
    *,
    concept_code: str,
    to_state: ConceptLifecycleState,
    via: ConceptTransitionVia,
    changed_by_kind: ChangedByKind,
    changed_by_name: str,
    reason: str,
) -> ConceptStateTransition:
    """개념 상태를 전환하고 기록 행 1건을 남긴다. 커밋은 호출자가 한다.

    허용 쌍과 경로는 `schema.concept_lifecycle.ALLOWED_TRANSITIONS`다. 거부되면 DB에 아무것도 쓰지
    않고
    `InvalidConceptTransitionError`을 던지며 ERROR 로그를 남긴다. 개념 행이 없으면
    `ConceptNotFoundError`.

    Args:
        changed_by_name: 규칙 이름 · 에이전트 이름 · 'Kiki' (kind에 맞는 이름).
        reason: 사유. 빈 문자열·공백만이면 거부한다(왜 바꿨는지 모르는 기록은 증거가 아니다).
    """
    current_kind = ChangedByKind(changed_by_kind).value
    via_value = ConceptTransitionVia(via).value
    to_value = ConceptLifecycleState(to_state).value
    name = changed_by_name.strip()
    why = reason.strip()

    # ── 1단계: DB를 읽기 전에 거를 수 있는 것 — 주체·사유·권한 ──────────────────────────────
    if not name:
        raise _reject(
            "변경 주체 이름이 비었다",
            concept_code=concept_code,
            from_state=None,
            to_state=to_value,
            via=via_value,
            changed_by_kind=current_kind,
        )
    if not why:
        raise _reject(
            "사유가 비었다",
            concept_code=concept_code,
            from_state=None,
            to_state=to_value,
            via=via_value,
            changed_by_kind=current_kind,
        )
    if via in KIKI_ONLY_VIA and changed_by_kind is not ChangedByKind.KIKI:
        raise _reject(
            "긴급 정지는 Kiki만 발동할 수 있다",
            concept_code=concept_code,
            from_state=None,
            to_state=to_value,
            via=via_value,
            changed_by_kind=current_kind,
        )

    # ── 2단계: 현재 상태를 행 잠금으로 읽는다(동시 전환 직렬화) ───────────────────────────
    current = (
        await session.execute(
            sa.select(ConceptContent.lifecycle_status)
            .where(ConceptContent.code == concept_code)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if current is None:
        logger.error("개념 상태 전환 거부 — concept=%s: 개념 행 없음", concept_code)
        raise ConceptNotFoundError(f"concept_content 행이 없다: {concept_code}")

    # ── 3단계: 전환표 — 쌍과 경로가 모두 맞아야 한다 ───────────────────────────────────────
    try:
        from_state = ConceptLifecycleState(current)
    except ValueError:
        # DB CHECK가 막으므로 정상 경로에선 오지 않는다. 오면 어휘 밖 값을 조용히 통과시키지 않는다.
        raise _reject(
            f"현재 상태가 어휘 밖이다: {current!r}",
            concept_code=concept_code,
            from_state=current,
            to_state=to_value,
            via=via_value,
            changed_by_kind=current_kind,
        ) from None

    allowed_vias = ALLOWED_TRANSITIONS.get((from_state, to_state))
    if allowed_vias is None:
        raise _reject(
            f"허용되지 않은 전환 {from_state.value} -> {to_value}",
            concept_code=concept_code,
            from_state=from_state.value,
            to_state=to_value,
            via=via_value,
            changed_by_kind=current_kind,
        )
    if via not in allowed_vias:
        raise _reject(
            f"{from_state.value} -> {to_value} 전환은 경로 '{via_value}'로 할 수 없다 "
            f"(허용 경로: {', '.join(sorted(v.value for v in allowed_vias))})",
            concept_code=concept_code,
            from_state=from_state.value,
            to_state=to_value,
            via=via_value,
            changed_by_kind=current_kind,
        )

    # ── 4단계: 상태 변경 + 기록(같은 트랜잭션) ─────────────────────────────────────────────
    # WHERE에 현재 상태를 다시 걸어 둔다 — 행 잠금이 있으므로 정상 경로에선 항상 1행이지만, 잠금이
    # 어긋나는 사고(다른 세션이 잠금 밖에서 바꿈)를 조용한 덮어쓰기가 아니라 실패로 만든다.
    # `RETURNING code`로 "정확히 1행 적용"을 확인한다(`Result`에는 rowcount가 선언돼 있지 않다).
    updated_code = (
        await session.execute(
            sa.update(ConceptContent)
            .where(ConceptContent.code == concept_code, ConceptContent.lifecycle_status == current)
            .values(lifecycle_status=to_value)
            .returning(ConceptContent.code)
        )
    ).scalar_one_or_none()
    if updated_code is None:
        raise ConceptTransitionError(f"상태 변경이 적용되지 않았다 (대상 0행): {concept_code}")

    record = ConceptStateTransition(
        concept_code=concept_code,
        from_state=from_state.value,
        to_state=to_value,
        changed_by_kind=current_kind,
        changed_by_name=name,
        via=via_value,
        reason=why,
    )
    session.add(record)
    await session.flush()
    logger.info(
        "개념 상태 전환 — concept=%s %s -> %s via=%s by=%s/%s",
        concept_code,
        from_state.value,
        to_value,
        via_value,
        current_kind,
        name,
    )
    return record


__all__ = [
    "ConceptNotFoundError",
    "ConceptTransitionError",
    "InvalidConceptTransitionError",
    "is_student_visible",
    "row_is_student_visible",
    "transition_concept_state",
]
