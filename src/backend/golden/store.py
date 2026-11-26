"""골든 패스 저장소(GP-6) — PostgreSQL golden 스키마의 학생·세션·턴 기록과 숙련도 갱신.

S22: T1 평가기 기록용 표 `golden.eval_log`가 하나 더 있다(턴 표에는 열을 더하지 않는다).
S32: T3 숙련도 섀도 표 `golden.mastery_shadow`가 하나 더 있다(학생 표에는 열을 더하지 않는다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.ext.asyncio import AsyncEngine

# 엔진은 골든 복사본을 쓴다(S20A 전이 의존 절단 · HARVEST.md) — 연결 주소는 WHYMATH_DATABASE_URL
from golden.db import get_engine

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

# S22(1단계 T1): 튜터 되묻기 1건에 대한 평가기 판정 기록. GOLDEN_T1_RUBRIC=1일 때만 쓴다.
# turns에 열을 더하지 않으려고 표를 따로 둔다(공유 계약의 표 3개는 그대로). 턴 1개에 판정 1개.
# 응답 문장은 여기에 다시 적지 않는다 — 문장은 turns.tutor_text에 이미 있고 turn_id로 잇는다.
eval_log = Table(
    "eval_log",
    metadata,
    Column("turn_id", BigInteger, primary_key=True),
    Column("verdict_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# S32(1단계 T3): 판정 1건마다 두 엔진(simple·bkt)의 숙련도를 1행씩 쌓는다(append-only).
# students에 열을 더하지 않으려고 표를 따로 둔다. 플래그 GOLDEN_MASTERY_ENGINE과 무관하게 늘 쓴다.
# - simple 행의 값 = 그 판정 뒤 students.mastery(반올림된 값)와 같다.
# - bkt 행의 값 = 반올림하지 않은 확률(다음 판정의 prior로 그대로 쓴다).
# - id는 같은 학생·엔진의 "가장 최근 행"을 고르는 순서 키다
#   (updated_at만으로는 같은 시각이 겹칠 수 있다).
mastery_shadow = Table(
    "mastery_shadow",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("nickname", Text, nullable=False),
    Column("engine", Text, nullable=False),
    Column("mastery", Float, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("problem_id", Text, nullable=False),
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
    """골든 엔진(연결 풀 없음 · NullPool)을 돌려준다.

    TestClient를 `with` 없이 쓰면 요청마다 새 이벤트 루프가 생긴다. 풀에 남은 asyncpg 연결은
    죽은 루프에 묶여 다음 요청에서 터지므로 풀을 쓰지 않는다(S4 실측 — `golden/db.py`).
    S20A 전에는 옛 `db.session.get_engine`을 `db_disable_pool=True`로 불렀다(같은 동작).
    """
    return get_engine()


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
) -> int:
    """답변 1건(학생 입력 + 튜터 응답 또는 판정)을 golden.turns에 기록하고 그 행의 id를 돌려준다.

    id는 S22 평가 기록(`golden.eval_log.turn_id`)이 턴을 가리킬 때 쓴다. 쓰지 않는 호출자는 버린다.
    """
    await ensure_schema()
    async with _engine().begin() as conn:
        turn_id = (
            await conn.execute(
                turns.insert()
                .values(
                    session_id=session_id,
                    problem_id=problem_id,
                    turn_no=turn_no,
                    student_text=student_text,
                    tutor_text=tutor_text,
                    kind=kind,
                    correct=correct,
                )
                .returning(turns.c.id)
            )
        ).scalar_one()
    return int(turn_id)


async def record_eval(turn_id: int, verdict: dict[str, object]) -> None:
    """평가 기록 1건을 golden.eval_log의 그 턴 행에 합친다(플래그가 켜졌을 때만 api가 부른다).

    - S22 T1 판정(`evaluator`·`leak`…)과 S27 T2 매칭(`t2_misconception_id`…)이
      같은 턴에 둘 다 쓰일 수 있다.
    - 턴 1개에 행 1개(PK `turn_id`)를 지키려고, 행이 이미 있으면 JSON 객체를 합친다
      (뒤에 쓴 쪽이 같은 키를 덮음).
      두 평가의 키 이름은 겹치지 않는다(T2는 `t2_` 접두).
    """
    await ensure_schema()
    statement = insert(eval_log).values(turn_id=turn_id, verdict_json=verdict)
    statement = statement.on_conflict_do_update(
        index_elements=[eval_log.c.turn_id],
        set_={"verdict_json": eval_log.c.verdict_json.op("||")(statement.excluded.verdict_json)},
    )
    async with _engine().begin() as conn:
        await conn.execute(statement)


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


async def get_shadow_mastery(nickname: str, engine: str) -> float | None:
    """섀도 표에서 이 학생·엔진의 가장 최근 숙련도. 기록이 없으면 None(호출자가 시작값을 정한다)."""
    await ensure_schema()
    async with _engine().connect() as conn:
        value = (
            await conn.execute(
                select(mastery_shadow.c.mastery)
                .where(mastery_shadow.c.nickname == nickname, mastery_shadow.c.engine == engine)
                .order_by(mastery_shadow.c.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return None if value is None else float(value)


async def record_mastery_shadow(
    *,
    nickname: str,
    session_id: uuid.UUID,
    problem_id: str,
    values: dict[str, float],
) -> None:
    """판정 1건의 엔진별 숙련도(엔진 이름 → 값)를 한 트랜잭션에 함께 쌓는다(엔진마다 1행)."""
    await ensure_schema()
    async with _engine().begin() as conn:
        await conn.execute(
            mastery_shadow.insert(),
            [
                {
                    "nickname": nickname,
                    "engine": engine,
                    "mastery": value,
                    "session_id": session_id,
                    "problem_id": problem_id,
                }
                for engine, value in values.items()
            ],
        )
