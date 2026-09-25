"""L2 학습 세션 writer — 서버 측 30분 유휴 규칙으로 `learning_session` 행을 연다·닫는다 (EOS-131).

────────────────────────────────────────────────────────────────────────────
왜 필요한가 — 세 소비처가 이 행 하나를 기다리고 있었다
────────────────────────────────────────────────────────────────────────────
`learning_session`은 테이블·조회·종료·삭제 표면만 있고 writer가 0건이었다(2026-09-16 실측).
S3-16 ③(2026-07-29)이 `focus_score`·`engagement_score`와 함께 행 writer까지 한 문장으로
미신설했는데, 그 사유("단일 스칼라가 정본 5분류와 축 불일치")는 **점수**에만 해당한다. 2026-09-24
결정(MEMORY "S3-16 ③ 부분 번복")으로 **행**은 만들고 점수는 계속 만들지 않는다. 이 행이 풀어 주는
소비처: 루프 KPI ①(`ops/loop_kpi_gate`), 파일럿 KPI2 재방문율(`harness/pilot_kpi_baseline`),
surrogate ③ 세션 완주율(`harness/surrogate_baseline_report`), 그리고 추천 기록의 학습자 결합
(`l2/recommendation_evidence` — `evidence_event.session_id → learning_session.user_id`).

────────────────────────────────────────────────────────────────────────────
규칙 — 클라 신호 없이 서버가 추론한다
────────────────────────────────────────────────────────────────────────────
인증된 학습 활동(`/me/next-problem`·`/me/attempts`·코치 턴)이 들어올 때마다 `touch`한다.
  - 그 학생의 **열린 서버 세션**이 있고 마지막 활동으로부터 `IDLE_GAP` 이내면 → 그 세션을 잇고
    `last_activity_at`을 갱신한다.
  - 열린 세션이 없거나 `IDLE_GAP`을 넘었으면 → 넘은 세션은 **마지막 활동 시각으로** 닫고
    (`ended_at = last_activity_at` — 닫는 *지금*이 아니다. 유휴 30분을 학습 시간으로 계상하면
    duration이 부풀어 오른다) 새 세션을 연다.
클라(Flutter)는 수정하지 않는다 — 앱 종료 신호는 모바일에서 신뢰할 수 없고(백그라운드 강제 종료·
배터리), 누락된 종료 신호가 세션을 영원히 열어 두는 상태를 만든다. 서버 규칙은 그 상태를 만들지
않는다: 다음 세션이 열릴 때(`touch`) 또는 조회·배치 시점(`close_idle_sessions`)에 유휴가 지난
세션이 닫힌다.

유휴 간격 30분의 근거는 `IDLE_GAP` 주석에 있다(상수 1곳).

**점수를 쓰지 않는다**: `focus_score`·`engagement_score`는 이 모듈이 절대 채우지 않는다(S3-16 ③
유지 — `tests/backend/l2/test_learning_session_writer.py`가 동결).

────────────────────────────────────────────────────────────────────────────
동시성 — 학생당 열린 세션 1개 (EOS-131 ⑩)
────────────────────────────────────────────────────────────────────────────
같은 학생의 요청 두 건이 거의 동시에 들어오면 둘 다 "열린 세션 없음"을 볼 수 있다. 행 잠금은
*아직 없는 행*을 잠글 수 없으므로 DB 제약으로 막는다 — 부분 유니크 인덱스
`uq_learning_session_open_per_user`(`user_id WHERE ended_at IS NULL AND last_activity_at IS NOT
NULL`, 마이그레이션 8e4c2a7f1b93). 새 세션은 `INSERT … ON CONFLICT DO NOTHING`으로 넣고, 졌으면
승자의 세션을 다시 읽어 합류한다. PostgreSQL은 충돌 대상이 *미커밋*이면 그 트랜잭션이 끝날 때까지
기다린 뒤 판정하므로, 패자는 승자의 커밋 이후 새 스냅샷으로 승자의 행을 본다(READ COMMITTED).

────────────────────────────────────────────────────────────────────────────
실패 정책 — 측정 좌석이 학습 요청을 깨지 않는다, 단 침묵하지 않는다
────────────────────────────────────────────────────────────────────────────
세션 행은 **측정 좌석**이다. 이 기록이 실패했다고 학생의 문제 추천·채점 제출·코치 턴을 실패시키면
의사결정 우선순위(학습 효과 > 비용·효율)를 거꾸로 적용하는 것이다. 그래서 서빙 경로는
`record_learning_activity`(never-break)를 부른다:
  - 작업 전체를 **SAVEPOINT**(`begin_nested`) 안에서 한다 — DB 오류가 나도 바깥 트랜잭션(추천
    기록·시도 적재)이 오염되지 않는다.
  - 실패하면 **예외 타입명**을 로그에 남기고(CLAUDE.md 침묵 실패 금지) 실패 횟수를 인프로세스로
    센다(`failure_count` — 외부 관측 인프라 의존 금지·이중 회계). 반환값은 `None`이며 호출자는 그
    활동을 세션에 결합하지 않는다(가짜 세션 id를 만들지 않는다).
판정·검증 경로(`touch_learning_session`)는 예외를 그대로 올린다 — 테스트와 배치가 실패를 본다.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

from sqlalchemy import CursorResult, Integer, func, select, update
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import LearningSession

_logger = logging.getLogger("whymath.l2.learning_session_writer")

IDLE_GAP: Final[timedelta] = timedelta(minutes=30)
"""세션 경계 유휴 간격 — 마지막 학습 활동으로부터 이 시간을 **넘으면**(`>`) 새 세션이다.

근거: 웹·앱 분석의 사실상 표준 세션 타임아웃이 30분이다(Google Analytics 기본 세션 타임아웃
30분 — 업계 리텐션 지표가 이 경계로 집계되므로 파일럿 KPI2 재방문율을 외부 벤치마크와 같은 단위로
읽을 수 있다). 교수학적으로도 한 문항 풀이·코치 대화 한 회차(돌아보기 포함)는 활동 사이 공백이
수 분 단위이고, 30분 넘게 아무 활동이 없으면 같은 앉은자리로 보기 어렵다. 이 값을 바꾸면 KPI ①
분모·KPI2 재방문율·세션 완주율이 전부 바뀌므로 MEMORY 결정 로그를 동반한다(2026-09-24 결정).
정확히 30분(`==`)은 같은 세션이다 — 경계 포함.
"""

_OPEN_SERVER_SESSION = (
    LearningSession.ended_at.is_(None),
    LearningSession.last_activity_at.is_not(None),
)
"""서버 writer가 관리하는 *열린* 세션의 조건 — 부분 유니크 인덱스의 WHERE와 **같아야 한다**.

`ON CONFLICT`가 이 인덱스를 추론하려면 `index_where`가 인덱스 술어와 일치해야 하고, 조회가 다른
범위를 보면 "열린 세션 없음 → INSERT → 충돌"이 영원히 반복된다. 그래서 한 곳에서 정의한다.
"""

_failure_count = 0


@dataclass(frozen=True, slots=True)
class SessionTouch:
    """`touch_learning_session` 결과 — 어떤 세션에 결합됐고, 무엇이 열리고 닫혔는가."""

    session_id: uuid.UUID
    #: 이번 활동이 새 세션을 열었는가(False = 기존 열린 세션을 이었다·경합에서 합류했다).
    opened: bool
    #: 유휴 초과로 이번에 닫힌 직전 세션(없으면 None).
    closed_previous: uuid.UUID | None = None


def failure_count() -> int:
    """이 프로세스에서 `record_learning_activity`가 삼킨 실패 횟수(인프로세스 회계)."""
    return _failure_count


def _now() -> datetime:
    """기록 시각(UTC aware). 테스트가 패치할 수 있게 함수로 뺀다."""
    return datetime.now(UTC)


def _close_values(last_activity_at: datetime, started_at: datetime | None) -> dict[str, Any]:
    """유휴 종료 값 — 종료 시각은 *마지막 활동*이다(닫는 시점이 아니다)."""
    values: dict[str, Any] = {"ended_at": last_activity_at}
    if started_at is not None:
        values["duration_seconds"] = max(0, int((last_activity_at - started_at).total_seconds()))
    return values


async def _lock_open_session(session: AsyncSession, user_id: uuid.UUID) -> LearningSession | None:
    """그 학생의 열린 서버 세션을 행 잠금과 함께 읽는다(없으면 None).

    `FOR UPDATE`는 *있는* 행의 동시 갱신(둘이 같이 닫고 둘이 같이 새로 열기)을 직렬화한다. *없는*
    행의 경합은 잠글 대상이 없으므로 부분 유니크 인덱스가 막는다(모듈 docstring 동시성 절).
    """
    result = await session.execute(
        select(LearningSession)
        .where(LearningSession.user_id == user_id, *_OPEN_SERVER_SESSION)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalars().first()


async def touch_learning_session(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> SessionTouch:
    """학습 활동 1건을 세션에 결합한다 — 잇거나, 닫고 새로 열거나(commit 0·flush만).

    커밋 경계는 호출자 책임이다(`recommendation_evidence` 관례). 예외를 삼키지 않는다 — 서빙
    경로는 `record_learning_activity`를 쓴다.
    """
    moment = now if now is not None else _now()
    if moment.tzinfo is None:
        raise ValueError("now는 timezone-aware여야 합니다(naive는 서버 로컬 TZ로 오해석된다).")

    closed: uuid.UUID | None = None
    current = await _lock_open_session(session, user_id)
    if current is not None:
        last = cast(datetime, current.last_activity_at)  # _OPEN_SERVER_SESSION이 NOT NULL 보장
        if moment - last <= IDLE_GAP:
            # 같은 세션을 잇는다. 시계가 뒤로 가도(요청 도착 순서 역전) 마지막 활동을
            # 되돌리지 않는다.
            if moment > last:
                current.last_activity_at = moment
                await session.flush()
            return SessionTouch(session_id=current.session_id, opened=False)
        # 유휴 초과 — 마지막 활동 시각으로 닫는다.
        for key, value in _close_values(last, current.started_at).items():
            setattr(current, key, value)
        await session.flush()
        closed = current.session_id

    new_id = uuid.uuid4()
    inserted = await session.execute(
        pg_insert(LearningSession)
        .values(
            session_id=new_id,
            user_id=user_id,
            started_at=moment,
            last_activity_at=moment,
        )
        .on_conflict_do_nothing(
            index_elements=[LearningSession.user_id],
            index_where=LearningSession.ended_at.is_(None)
            & LearningSession.last_activity_at.is_not(None),
        )
        .returning(LearningSession.session_id)
    )
    won = inserted.scalar_one_or_none()
    if won is not None:
        return SessionTouch(session_id=won, opened=True, closed_previous=closed)

    # 경합에서 졌다 — 승자의 세션(이제 커밋돼 보인다)에 합류한다.
    winner = await _lock_open_session(session, user_id)
    if winner is None:
        # 충돌했는데 열린 세션이 안 보인다 = 인덱스 술어와 조회 범위가 어긋났다(프로그래밍 오류).
        raise RuntimeError(
            "learning_session 삽입이 충돌했으나 열린 서버 세션을 찾지 못했다 — "
            "부분 유니크 인덱스 술어와 _OPEN_SERVER_SESSION이 어긋났는지 확인하라."
        )
    if winner.last_activity_at is None or moment > winner.last_activity_at:
        winner.last_activity_at = moment
        await session.flush()
    return SessionTouch(session_id=winner.session_id, opened=False, closed_previous=closed)


async def record_learning_activity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> uuid.UUID | None:
    """서빙 경로용 never-break 래퍼 — 결합된 세션 id, 실패 시 None(예외 타입명 로그).

    SAVEPOINT 안에서 돌리므로 실패가 바깥 트랜잭션을 오염시키지 않는다(모듈 docstring 실패 정책).
    """
    global _failure_count
    try:
        async with session.begin_nested():
            touched = await touch_learning_session(session, user_id=user_id, now=now)
        return touched.session_id
    except Exception as exc:  # noqa: BLE001 — 측정 좌석 never-break(타입명 로그·인프로세스 회계)
        _failure_count += 1
        _logger.warning(
            "학습 세션 기록 실패(%s) — 학습 요청은 계속 진행하고 이 활동은 세션에 결합하지 않는다"
            " (누적 %d회).",
            type(exc).__name__,
            _failure_count,
        )
        return None


async def close_idle_sessions(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    user_id: uuid.UUID | None = None,
) -> int:
    """유휴 간격이 지난 열린 서버 세션을 마지막 활동 시각으로 닫는다 — 닫은 행 수(commit 0).

    "다음 활동이 영영 오지 않는 학생"의 세션이 영원히 열려 있지 않게 하는 조회·배치 시점 확정이다.
    `user_id`를 주면 그 학생만(본인 조회 경로), 안 주면 전체(배치 경로).
    """
    moment = now if now is not None else _now()
    conds = [*_OPEN_SERVER_SESSION, LearningSession.last_activity_at < moment - IDLE_GAP]
    if user_id is not None:
        conds.append(LearningSession.user_id == user_id)
    result = await session.execute(
        update(LearningSession)
        .where(*conds)
        .values(
            ended_at=LearningSession.last_activity_at,
            duration_seconds=func.greatest(
                0,
                sql_cast(
                    func.extract(
                        "epoch", LearningSession.last_activity_at - LearningSession.started_at
                    ),
                    Integer,
                ),
            ),
        )
        .execution_options(synchronize_session=False)
    )
    return cast("CursorResult[Any]", result).rowcount or 0


async def close_idle_sessions_best_effort(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    user_id: uuid.UUID | None = None,
) -> int:
    """조회 표면용 never-break 래퍼 — 실패하면 0(예외 타입명 로그·인프로세스 회계)."""
    global _failure_count
    try:
        async with session.begin_nested():
            return await close_idle_sessions(session, now=now, user_id=user_id)
    except Exception as exc:  # noqa: BLE001 — 조회를 깨지 않는다(타입명 로그)
        _failure_count += 1
        _logger.warning(
            "유휴 세션 종료 확정 실패(%s) — 조회는 계속 진행한다 (누적 %d회).",
            type(exc).__name__,
            _failure_count,
        )
        return 0


__all__ = [
    "IDLE_GAP",
    "SessionTouch",
    "close_idle_sessions",
    "close_idle_sessions_best_effort",
    "failure_count",
    "record_learning_activity",
    "touch_learning_session",
]
