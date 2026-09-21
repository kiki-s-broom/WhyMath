"""SEC-35 축 ② — `learner_state` 보유 학생의 삭제권이 **FK 위반으로 터지지 않는가**(실 PG).

이 파일이 겨냥하는 것은 "조용한 파기 누락"이 아니라 그보다 나쁜 상태 — **삭제 요청 자체의
실패**다. `learner_state.learner_id`는 `user_profile.user_id`를 `ondelete` 없이(=NO ACTION)
참조하므로, 그 행이 하나라도 있으면 `erase_user()` 마지막의 `delete(UserProfile)`이
`ForeignKeyViolationError`를 내고 **단일 트랜잭션 전체가 롤백된다**. 즉 진단을 완료해
`learner_state` 행을 가진 학생(= 정상 학습 경로를 밟은 모든 학생)은 GDPR 삭제권 행사가 *항상*
실패했고, 부분 삭제조차 아닌 **0건 삭제**로 끝났다.

수정 전 실측(2026-09-18, 실 PG pg16 · main `a34d31d4` + learner_state 미등재 상태):
  RESULT=RAISED IntegrityError
  ForeignKeyViolationError: update or delete on table "user_profile" violates foreign key
  constraint "fk_learner_state_user_profile" on table "learner_state"
  AFTER learner_state_rows=1 user_profile_rows=1   ← 전체 롤백·아무것도 안 지워짐

검사 2종(둘 다 있어야 의미가 있다):
  ① `test_erase_user_succeeds_with_learner_state_row` — 수정 후 성립(삭제가 실제로 된다).
  ② `test_user_profile_delete_alone_still_blocked_by_learner_state_fk` — **전제 동결**.
     FK가 여전히 NO ACTION임을 실 DB에서 단언한다. 이것이 red가 되는 날(= 누군가 마이그레이션
     으로 `ondelete=CASCADE`를 걸었다) ①만으론 그 변화가 보이지 않는다 — ①은 계획 경유 삭제라
     CASCADE가 붙어도 계속 green이기 때문이다. 즉 ②가 없으면 "왜 계획 등재가 필요한가"라는
     근거가 코드에서 사라진 뒤에도 아무도 모른다.

hermetic 아님(`@pytest.mark.integration`) — CI의 `backend-migrations` 잡(실 PG service ·
`pytest -m integration`)이 집행 지점이다. PG 미도달이면 graceful skip(기존 `test_erasure.py`
통합 테스트와 동형).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import Settings
from whymath_backend.db.models.learner_state import (
    PROVISIONED_BY_DIAGNOSIS_CAPTURE,
    LearnerStateRecord,
)
from whymath_backend.db.models.user import UserProfile
from whymath_backend.privacy.erasure import _ERASURE_PLAN, erase_user
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_SECRET = "integration-jwt-secret-0123456789abcdef"


def _settings() -> Settings:
    return Settings(jwt_secret_key=SecretStr(_SECRET))


async def _pg_reachable() -> bool:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — 도달성 프로브(미도달이면 skip·원인 무관)
        return False
    finally:
        await engine.dispose()


def _build_user(user_id: uuid.UUID) -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(
            user_id=user_id,
            persona_primary=Persona.A_일반고고3,
            nickname="파기학생",
            email_hash=f"HASH-{user_id.hex[:8]}",
            is_minor=True,
        )
    )


async def _seed_user_with_learner_state(
    sm: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> None:
    """user_profile 1행 + 그것을 NO ACTION FK로 물고 있는 learner_state 1행."""
    async with sm() as session:
        session.add(_build_user(user_id))
        await session.flush()
        session.add(
            LearnerStateRecord(
                learner_id=user_id,
                curriculum_id="2022-math",
                current_objective_id="obj-sec35",
                provisioned_by=PROVISIONED_BY_DIAGNOSIS_CAPTURE,
            )
        )
        await session.commit()


async def _cleanup(user_id: uuid.UUID) -> None:
    engine = create_async_engine(_settings().database_url)
    try:
        async with engine.begin() as conn:
            for tbl, col in (
                ("learner_state", "learner_id"),
                ("deletion_audit", "user_id"),
                ("user_profile", "user_id"),
            ):
                await conn.execute(text(f"DELETE FROM {tbl} WHERE {col} = :k"), {"k": str(user_id)})
    finally:
        await engine.dispose()


def test_learner_state_is_registered_in_erasure_plan() -> None:
    """hermetic 선행 단언 — 계획 등재가 사라지면 아래 통합 검사가 skip된 환경에서도 red."""
    planned = {model.__tablename__: column for model, column in _ERASURE_PLAN}
    assert planned.get("learner_state") == "learner_id", (
        "learner_state가 _ERASURE_PLAN에서 빠졌거나 소유 컬럼이 바뀌었다 — "
        "이 상태에서는 진단 완료 학생의 삭제권 요청이 FK 위반으로 전면 실패한다(SEC-35)."
    )


@pytest.mark.integration
def test_erase_user_succeeds_with_learner_state_row() -> None:
    """① 수정 후 성립 — learner_state 행이 있어도 삭제가 터지지 않고 실제로 지워진다."""
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            await _seed_user_with_learner_state(sm, uid)

            async with sm() as session:
                report = await erase_user(session, user_id=uid)
                await session.commit()  # commit은 호출자
                # 보고에 *학습자 상태가 명시적으로 계상*되어야 한다 — CASCADE 부수효과로
                # 사라진 것과 계획이 지운 것을 보고가 구분하지 못하면 감사 가치가 없다.
                assert report.deleted_counts["learner_state"] == 1
                assert report.user_profile_deleted == 1

            async with sm() as session:
                remaining = await session.scalar(
                    select(func.count())
                    .select_from(LearnerStateRecord)
                    .where(LearnerStateRecord.learner_id == uid)
                )
                assert remaining == 0, "learner_state 행이 잔존한다(파기 누락)."
                assert await session.get(UserProfile, uid) is None
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid))


@pytest.mark.integration
def test_user_profile_delete_alone_still_blocked_by_learner_state_fk() -> None:
    """② 전제 동결 — FK는 여전히 NO ACTION이다(계획 등재가 *필요한* 이유의 실 DB 근거).

    계획을 우회해 `user_profile`만 지우면 실패해야 한다. 이 단언이 red가 되면 마이그레이션이
    `ondelete`를 바꾼 것이며, 그때는 계획 등재의 근거가 달라지므로 위 모듈 docstring과
    `erasure.py`의 SEC-35 주석을 함께 갱신해야 한다(자동 CASCADE가 생겼다고 계획에서 빼는 것이
    옳다는 뜻은 아니다 — 보고 일관성은 명시 삭제 쪽에 있다 · EvidenceLink 선례).
    """
    if not asyncio.run(_pg_reachable()):
        pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀")

    uid = uuid.uuid4()

    async def _run() -> None:
        engine = create_async_engine(_settings().database_url)
        try:
            sm = async_sessionmaker(engine, expire_on_commit=False)
            await _seed_user_with_learner_state(sm, uid)

            async with sm() as session:
                with pytest.raises(IntegrityError) as excinfo:
                    await session.execute(
                        text("DELETE FROM user_profile WHERE user_id = :k"), {"k": str(uid)}
                    )
                    await session.flush()
                await session.rollback()
            # 예외 타입명이 아니라 *제약 이름*까지 확인한다 — 다른 FK 위반이 같은 타입으로
            # 올라와도 통과해 버리면 이 테스트는 learner_state 축을 안 밟은 것이다.
            assert "learner_state" in str(
                excinfo.value
            ), f"learner_state FK가 아닌 다른 위반이 잡혔다: {str(excinfo.value)[:200]}"
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(_cleanup(uid))
