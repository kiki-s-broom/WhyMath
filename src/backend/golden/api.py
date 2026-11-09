"""골든 패스 HTTP 엔드포인트 3개(session · next · answer, 접두 /golden) — S4가 채운다.

서버: `uvicorn golden.api:app`. 옛 `create_app`에는 등록하지 않는다(파사드 분리 — 옛 앱은 그대로).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from golden import grade, problems, store, tutor

# 한 문제에서 쓸 수 있는 튜터 되묻기 최대 횟수(공유 계약)
MAX_TUTOR_TURNS = 3

router = APIRouter(prefix="/golden")


class SessionIn(BaseModel):
    """POST /golden/session 본문 — 학생 식별자는 닉네임 문자열뿐이다."""

    nickname: str = Field(min_length=1, max_length=20)


class AnswerIn(BaseModel):
    """POST /golden/answer 본문."""

    session_id: str
    problem_id: str
    text: str


def _parse_session_id(raw: str) -> uuid.UUID:
    """UUID 모양이 아니면 '알 수 없는 세션'과 같게 404로 답한다."""
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="알 수 없는 session_id") from None


async def _require_session(raw: str) -> store.SessionRow:
    """세션을 찾고, 없으면 404."""
    row = await store.get_session(_parse_session_id(raw))
    if row is None:
        raise HTTPException(status_code=404, detail="알 수 없는 session_id")
    return row


@router.post("/session")
async def start_session(body: SessionIn) -> dict[str, object]:
    """GP-1 세션 시작 — 같은 닉네임이면 숙련도를 이어받고 session_id만 새로 발급한다."""
    session_id, mastery = await store.create_session(body.nickname)
    return {"session_id": str(session_id), "nickname": body.nickname, "mastery": mastery}


@router.get("/next")
async def next_problem(session_id: str) -> dict[str, object]:
    """GP-2 문제 제시 — 세션 cursor 위치의 문제. 30개를 다 풀면 처음부터 순환한다.

    조회만 하고 cursor를 옮기지 않는다(판정이 나야 다음 문제로 넘어간다).
    """
    row = await _require_session(session_id)
    items = problems.load_problems()
    position = row.cursor % len(items)
    return problems.public_view(items[position], index=position + 1, total=len(items))


@router.post("/answer")
async def answer(body: AnswerIn) -> dict[str, object]:
    """GP-3 답변 → (오답) GP-4 튜터 되묻기 / (정답 또는 3턴 소진) GP-5 판정.

    판정 순서는 고정: ①먼저 채점 ②정답이면 graded ③오답이고 튜터 턴 3회 미만이면 tutor_turn
    ④오답이고 3회를 이미 썼으면 graded(정답 공개, 비난 표현 금지).
    """
    row = await _require_session(body.session_id)
    items = problems.load_problems()
    problem = next((p for p in items if p["id"] == body.problem_id), None)
    if problem is None:
        raise HTTPException(status_code=404, detail="알 수 없는 problem_id")

    history = await store.open_turns(row.session_id, problem["id"])
    turns_used = len(history)  # 이 문제에서 이미 쓴 튜터 턴 수(0~3)

    # ① 채점 먼저 (S4: grade.is_correct는 항상 False인 스텁 — S5에서 교체)
    correct = grade.is_correct(problem, body.text)

    if correct:
        # ② 정답 — 몇 턴째든 판정. 숙련도 +0.10 갱신은 S5(GP-6)가 붙인다.
        feedback = "맞았어! 어떻게 풀었는지 한 문장으로 설명해 볼 수 있을까?"
        return await _graded(row, problem, body.text, True, turns_used, feedback)

    if turns_used < MAX_TUTOR_TURNS:
        # ③ 오답 + 튜터 턴 남음 → 되묻기
        reply = await tutor.ask(problem, history, body.text)
        turn_no = turns_used + 1
        await store.record_turn(
            session_id=row.session_id,
            problem_id=problem["id"],
            turn_no=turn_no,
            student_text=body.text,
            tutor_text=reply.message,
            kind="tutor_turn",
            correct=False,
        )
        response: dict[str, object] = {
            "kind": "tutor_turn",
            "message": reply.message,
            "turn": turn_no,
        }
        if reply.degraded:
            response["degraded"] = True
        return response

    # ④ 오답 + 튜터 턴 3회 소진 → 정답을 알려 주며 판정. 숙련도 −0.05 갱신은 S5(GP-6)가 붙인다.
    feedback = f"정답은 {problem['answer']}이야. 함께 생각해 줘서 고마워, 다음 문제로 가 보자."
    return await _graded(row, problem, body.text, False, turns_used, feedback)


async def _graded(
    row: store.SessionRow,
    problem: problems.Problem,
    student_text: str,
    correct: bool,
    turns_used: int,
    feedback: str,
) -> dict[str, object]:
    """판정 응답 — 턴을 기록하고, 지금 보던 문제라면 cursor를 다음 문제로 옮긴다."""
    await store.record_turn(
        session_id=row.session_id,
        problem_id=problem["id"],
        turn_no=turns_used,
        student_text=student_text,
        tutor_text=feedback,
        kind="graded",
        correct=correct,
    )
    items = problems.load_problems()
    if items[row.cursor % len(items)]["id"] == problem["id"]:
        await store.advance_cursor(row.session_id)
    mastery = await store.get_mastery(row.nickname)
    return {
        "kind": "graded",
        "correct": correct,
        "mastery": mastery,
        "turns_used": turns_used,
        "feedback": feedback,
    }


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """앱 시작 시 golden 스키마와 표 3개를 만든다."""
    await store.ensure_schema()
    yield


app = FastAPI(title="WhyMath Golden Path", lifespan=lifespan)
app.include_router(router)
