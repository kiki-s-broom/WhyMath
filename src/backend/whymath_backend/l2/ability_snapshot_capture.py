"""L2 — 채점 경계의 전과목 θ 스냅샷 자동 적재 (EOS-125 처분 (가)).

왜 필요한가: `GET /v1/me/learner-state`의 `general_ability`는 `ability_snapshot` 최신 행을 읽는다
(`l2/ability_tracking.get_current_theta`). 그런데 그 행을 만드는 경로는 수동 캡처
(`POST /v1/me/ability/snapshots`)와 학습 세션 종료(`PATCH /sessions/{id}/end`)뿐이라, 채점 루프만
도는 학습자는 상태 합성 표면에서 θ가 **항상 null**이었다(P-15 페르소나 3인 14회 전원). 같은 순간
`GET /v1/me/next-problem`은 θ를 즉석 추정해 싣는다 — 능력 추정이 없는 것이 아니라 *적재되지 않아*
한쪽 표면에서만 사라졌다.

처분: **(가) 채점이 끝나는 자연 경계에서 적재한다.** (나) 읽기측을 즉석 추정으로 바꾸면 θ가 어느
스냅샷에서 왔는지(`TraceBasis.ability_snapshot_id` — EOS-132 추적 고리)를 잃는다. (다) 현행 유지는
결함을 문서화할 뿐 고치지 않는다.

중복·비용 판정 — 매 채점마다 쓰지 않는다:
- 스냅샷 없음 → 첫 채점 직후 1건(콜드스타트 해소. 응답 1건짜리 θ는 SE·응답수가 함께 실려
  coach 노이즈 가드가 거른다).
- 스냅샷 있음 → 마지막 스냅샷 이후 채점이 `CAPTURE_STRIDE`건 이상 쌓였을 때만 1건.
- 판정에는 `COUNT` 1회만 쓰고, 전체 이력을 읽는 추정(`estimate_global_ability`)은 적재가 확정된
  뒤에만 돈다 — 한 학습자의 채점당 추가 비용은 가벼운 조회 2회다.

범위(명시): **전과목 θ(concept_id NULL)만** 적재한다. 개념별 θ(`/ability/by-concept` 곡선)는
세션 종료·수동 캡처가 계속 맡는다 — 이 모듈은 *적재 경계*만 다루며 IRT 추정기·θ 척도는 건드리지
않는다(EOS-125 ⑤). 개념별 적재 코드는 L5(`api/me`)에 있어 L2에서 부를 수 없다(역방향 의존).

never-break: 적재 실패가 채점 응답을 깨뜨리지 않는다. 실패는 **예외 타입명**과 함께 경고로 남기고
(침묵 실패 금지) 결과 `FAILED`로 호출부에 알린다. 호출 시점은 이번 attempt가 commit된 뒤다.
"""

from __future__ import annotations

import enum
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.assessment import AbilitySnapshot
from whymath_backend.l2.ability_estimation import estimate_global_ability
from whymath_backend.l2.ability_tracking import get_current_ability
from whymath_backend.schema.assessment import AbilitySnapshot as AbilitySnapshotSchema

_logger = logging.getLogger("whymath.l2.ability_snapshot_capture")

# 마지막 스냅샷 이후 이만큼 채점이 쌓이면 다시 적재한다. 5는 성장 곡선이 "문항 몇 개마다 한 점"
# 으로 읽히면서 학습자당 행 수가 채점 수의 1/5로 묶이는 값이다(세션 종료 적재와 합쳐도 같은
# 곡선 위에 놓인다). 조정은 이 상수 하나로 한다.
CAPTURE_STRIDE = 5


class AbilityCaptureOutcome(enum.StrEnum):
    """적재 판정 결과 — 호출부·테스트가 "왜 안 썼는가"를 구분하게 한다(침묵 방지)."""

    CAPTURED = "captured"
    """스냅샷 1건을 적재했다."""

    NOT_DUE = "not_due"
    """마지막 스냅샷 이후 채점이 stride 미만이라 건너뛰었다(정상)."""

    NO_RESPONSES = "no_responses"
    """θ 추정에 쓸 응답이 없다(난이도 b를 못 정하는 문항뿐) — 빈 θ는 적재하지 않는다."""

    FAILED = "failed"
    """적재 중 예외 — 경고를 남기고 삼켰다(채점 응답은 정상)."""


async def _count_graded_attempts(session: AsyncSession, user_id: uuid.UUID) -> int:
    """채점된 시도 수 — 추정의 응답 후보와 같은 기준(`is_correct IS NOT NULL`)."""
    stmt = select(func.count()).where(
        ProblemAttempt.user_id == user_id,
        ProblemAttempt.is_correct.isnot(None),
    )
    return int((await session.execute(stmt)).scalar_one())


async def capture_global_ability_if_due(
    session: AsyncSession, user_id: uuid.UUID
) -> AbilityCaptureOutcome:
    """채점 직후 호출 — 적재 시점이 되었으면 전과목 θ 스냅샷 1건을 적재·commit한다.

    호출 전제: 이번 attempt가 이미 commit되었다(집계에 이번 행이 포함돼야 한다). 읽기 2회
    (최신 전과목 스냅샷·채점 수) 후 적재가 필요할 때만 추정과 쓰기가 일어난다.
    """
    try:
        latest = await get_current_ability(session, user_id)  # concept_id None=전과목
        graded = await _count_graded_attempts(session, user_id)
        if latest is not None and graded - latest.response_count < CAPTURE_STRIDE:
            return AbilityCaptureOutcome.NOT_DUE
        theta, se, count = await estimate_global_ability(session, user_id)
        if count == 0:
            return AbilityCaptureOutcome.NO_RESPONSES
        session.add(
            AbilitySnapshot.from_schema(
                AbilitySnapshotSchema(
                    user_id=user_id,
                    theta=theta,
                    standard_error=se,
                    response_count=count,
                )
            )
        )
        await session.commit()
        return AbilityCaptureOutcome.CAPTURED
    except Exception as exc:  # noqa: BLE001 — never-break: 적재 실패가 채점 응답을 깨지 않는다.
        _logger.warning(
            "θ 스냅샷 자동 적재 실패 — 채점은 정상(EOS-125) exc_type=%s", type(exc).__name__
        )
        try:
            await session.rollback()
        except Exception as rollback_exc:  # noqa: BLE001 — 롤백 실패도 삼키되 타입은 남긴다.
            _logger.warning(
                "θ 스냅샷 적재 실패 후 롤백도 실패(EOS-125) exc_type=%s",
                type(rollback_exc).__name__,
            )
        return AbilityCaptureOutcome.FAILED


__all__ = ["CAPTURE_STRIDE", "AbilityCaptureOutcome", "capture_global_ability_if_due"]
