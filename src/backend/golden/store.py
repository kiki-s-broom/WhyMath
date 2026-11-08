"""골든 패스 저장소(GP-6) — PostgreSQL golden 스키마의 학생·세션·턴 기록과 숙련도 갱신."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import UUID, insert
from sqlalchemy.ext.asyncio import AsyncEngine

# 옛 코드에서 가져온 것은 엔진 하나뿐이다(HARVEST.md) — 연결 URL은 옛 Settings(WHYMATH_DATABASE_URL)
from whymath_backend.config import get_settings
from whymath_backend.db.session import get_engine

# 공유 계약의 표 3개 — Alembic 리비전 없이 앱 시작 시 create_all로 만든다
metadata = MetaData(schema="golden")

students = Table(
    "students",
    metadata,
    Column("nickname", Text, primary_key=True),
    Column("mastery", Numeric(3, 2), nullable=False, server_default=text("0")),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

sessions = Table(
    "sessions",
    metadata,
    Column("session_id", UUID(as_uuid=True), primary_key=True),
    Column("nickname", Text, nullable=False),
    Column("cursor", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

turns = Table(
    "turns",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("problem_id", Text, nullable=False),
    Column("turn_no", Integer, nullable=False),
    Column("student_text", Text, nullable=False),
    Column("tutor_text", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("correct", Boolean, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

_schema_ready = False


@dataclass(frozen=True)
class SessionRow:
    """golden.sessions 1행."""

    session_id: uuid.UUID
    nickname: str
    cursor: int


@dataclass(frozen=True)
class TurnRow:
    """golden.turns 1행 중 튜터가 대화 맥락으로 쓰는 부분."""

    turn_no: int
    student_text: str
    tutor_text: str
    kind: str


def _engine() -> AsyncEngine:
    """옛 get_engine()을 연결 풀 없이(NullPool) 부른다.

    TestClient를 `with` 없이 쓰면 요청마다 새 이벤트 루프가 생긴다. 풀에 남은 asyncpg 연결은
    죽은 루프에 묶여 다음 요청에서 터지므로, 옛 설정의 db_disable_pool을 켠 사본을 넘긴다.
    (엔진이 이미 만들어져 있으면 get_engine은 넘긴 설정을 무시한다 — 골든 앱 프로세스에서는
    이 함수가 첫 호출자다.)
    """
    return get_engine(get_settings().model_copy(update={"db_disable_pool": True}))


async def ensure_schema() -> None:
    """`CREATE SCHEMA IF NOT EXISTS golden` + create_all. 앱 시작(lifespan)과 첫 사용 때 부른다.

    TestClient를 `with` 없이 쓰면 lifespan이 돌지 않으므로, 저장소 함수가 첫 호출에서 한 번 더
    부른다(이미 만들었으면 건너뛴다).
    """
    global _schema_ready
    if _schema_ready:
        return
    async with _engine().begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS golden"))
        await conn.run_sync(metadata.create_all)
    _schema_ready = True


def _to_float(value: Decimal | float | None) -> float:
    """numeric(3,2) 값을 float로 바꾼다(없으면 0.0)."""
    return float(value) if value is not None else 0.0


async def create_session(nickname: str) -> tuple[uuid.UUID, float]:
    """세션을 새로 발급한다. 같은 닉네임이 다시 오면 숙련도는 이어받고 session_id만 새로 만든다."""
    await ensure_schema()
    session_id = uuid.uuid4()
    async with _engine().begin() as conn:
        await conn.execute(
            insert(students)
            .values(nickname=nickname)
            .on_conflict_do_nothing(index_elements=["nickname"])
        )
        await conn.execute(sessions.insert().values(session_id=session_id, nickname=nickname))
        mastery = (
            await conn.execute(select(students.c.mastery).where(students.c.nickname == nickname))
        ).scalar_one()
    return session_id, _to_float(mastery)


async def get_session(session_id: uuid.UUID) -> SessionRow | None:
    """세션 1행을 돌려준다. 없으면 None."""
    await ensure_schema()
    async with _engine().connect() as conn:
        row = (
            await conn.execute(
                select(sessions.c.session_id, sessions.c.nickname, sessions.c.cursor).where(
                    sessions.c.session_id == session_id
                )
            )
        ).first()
    if row is None:
        return None
    return SessionRow(session_id=row.session_id, nickname=row.nickname, cursor=row.cursor)


async def advance_cursor(session_id: uuid.UUID) -> int:
    """다음 문제로 넘어간다(cursor + 1). 새 cursor를 돌려준다. 순환은 호출자가 문항 수로 나눈다."""
    await ensure_schema()
    async with _engine().begin() as conn:
        new_cursor = (
            await conn.execute(
                update(sessions)
                .where(sessions.c.session_id == session_id)
                .values(cursor=sessions.c.cursor + 1)
                .returning(sessions.c.cursor)
            )
        ).scalar_one()
    return int(new_cursor)


async def record_turn(
    *,
    session_id: uuid.UUID,
    problem_id: str,
    turn_no: int,
    student_text: str,
    tutor_text: str,
    kind: str,
    correct: bool | None,
) -> None:
    """답변 1건(학생 입력 + 튜터 응답 또는 판정)을 golden.turns에 기록한다."""
    await ensure_schema()
    async with _engine().begin() as conn:
        await conn.execute(
            turns.insert().values(
                session_id=session_id,
                problem_id=problem_id,
                turn_no=turn_no,
                student_text=student_text,
                tutor_text=tutor_text,
                kind=kind,
                correct=correct,
            )
        )


async def open_turns(session_id: uuid.UUID, problem_id: str) -> list[TurnRow]:
    """이 세션에서 이 문제를 지금 풀고 있는 동안의 튜터 턴 목록(마지막 판정 이후 것만).

    30문항을 돌고 같은 문제가 다시 나오면, 지난번 판정 이전의 턴은 세지 않는다.
    """
    await ensure_schema()
    async with _engine().connect() as conn:
        rows = (
            await conn.execute(
                select(turns.c.turn_no, turns.c.student_text, turns.c.tutor_text, turns.c.kind)
                .where(turns.c.session_id == session_id, turns.c.problem_id == problem_id)
                .order_by(turns.c.id)
            )
        ).all()
    current: list[TurnRow] = []
    for row in rows:
        if row.kind == "graded":
            current = []  # 지난 판정 이전 턴은 버린다
        else:
            current.append(
                TurnRow(
                    turn_no=row.turn_no,
                    student_text=row.student_text,
                    tutor_text=row.tutor_text,
                    kind=row.kind,
                )
            )
    return current


async def get_mastery(nickname: str) -> float:
    """학생의 숙련도(0.0~1.0). 학생 행이 없으면 0.0."""
    await ensure_schema()
    async with _engine().connect() as conn:
        value = (
            await conn.execute(select(students.c.mastery).where(students.c.nickname == nickname))
        ).scalar_one_or_none()
    return _to_float(value)


async def set_mastery(nickname: str, value: float) -> float:
    """숙련도를 0.0~1.0으로 잘라내고 소수 둘째 자리로 반올림해 저장한다. 저장한 값을 돌려준다."""
    await ensure_schema()
    clamped = round(min(1.0, max(0.0, value)), 2)
    async with _engine().begin() as conn:
        await conn.execute(
            update(students)
            .where(students.c.nickname == nickname)
            .values(mastery=Decimal(str(clamped)), updated_at=func.now())
        )
    return clamped
