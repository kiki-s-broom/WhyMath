"""골든 패스 HTTP 엔드포인트 3개(session · next · answer, 접두 /golden) — S4가 채운다.

서버: `uvicorn golden.api:app`. 옛 `create_app`에는 등록하지 않는다(파사드 분리 — 옛 앱은 그대로).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from golden import grade, problems, store, tutor

# 한 문제에서 쓸 수 있는 튜터 되묻기 최대 횟수(공유 계약). 튜터도 "몇 번째 되묻기인지"를
# 알아야 해서(S10) 값은 tutor 모듈 한 곳에 두고 여기서 가져다 쓴다.
MAX_TUTOR_TURNS = tutor.MAX_TUTOR_TURNS

# 숙련도 갱신 폭(공유 계약 — 맞으면 +0.10, 틀리면 −0.05. 잘라내기·반올림은 store.set_mastery가 한다)
MASTERY_GAIN = 0.10
MASTERY_LOSS = 0.05

# graded 응답의 한 줄 피드백(지시서 S5 — 비난 표현 금지)
FEEDBACK_CORRECT = "맞았어요. 다음 문제로 가 볼까요?"
FEEDBACK_WRONG = "이번 문제의 답은 {answer}{copula}. 다음 문제에서 다시 해 봐요."

# 소리 내어 읽을 때 끝소리에 받침이 있는 숫자: 영·일·삼·육·칠·팔
# (끝자리 0은 10·20·100도 십·백으로 끝나 받침이 있다). 2·4·5·9(이·사·오·구)는 받침이 없다.
_BATCHIM_DIGITS = frozenset("013678")

# 분수 `a/b`는 "b분의 a"로 읽어 분자로 끝난다(`-3/2` → "이분의 삼")
_FRACTION_TAIL = re.compile(r"([0-9x]+)/[0-9]+$")


def _copula(answer: str) -> str:
    """정답 뒤에 붙일 말 — 끝소리에 받침이 있으면 "이었어요", 없으면 "였어요".

    S10: "답은 8였어요"(S9 17행 · S11 sim_no-setup 21행 등) 조사 오류를 고친다.
    정답은 수(`-12`·`3/2`) 또는 x만 쓰는 식(`2*x + 1`)이다. `x`(엑스)는 받침이 없다.
    """
    s = answer.strip()
    fraction = _FRACTION_TAIL.search(s)
    last = fraction.group(1)[-1] if fraction else s[-1:]
    return "이었어요" if last in _BATCHIM_DIGITS else "였어요"


def wrong_feedback(answer: str) -> str:
    """3턴을 다 쓰고도 틀렸을 때의 한 줄 — 정답은 알려 주되 비난 표현은 쓰지 않는다."""
    return FEEDBACK_WRONG.format(answer=answer, copula=_copula(answer))


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

    # ① 채점 먼저 (GP-5 — SymPy 비교)
    correct = grade.is_correct(problem, body.text)

    if correct:
        # ② 정답 — 몇 턴째든 판정. 숙련도 +0.10(GP-6)
        return await _graded(row, problem, body.text, True, turns_used, FEEDBACK_CORRECT)

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

    # ④ 오답 + 튜터 턴 3회 소진 → 정답을 알려 주며 판정. 숙련도 −0.05(GP-6)
    feedback = wrong_feedback(problem["answer"])
    return await _graded(row, problem, body.text, False, turns_used, feedback)


async def _graded(
    row: store.SessionRow,
    problem: problems.Problem,
    student_text: str,
    correct: bool,
    turns_used: int,
    feedback: str,
) -> dict[str, object]:
    """판정 응답 — 턴 기록 → 숙련도 갱신 → 지금 보던 문제라면 cursor를 다음 문제로 옮긴다."""
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
    # GP-6 숙련도 갱신: 맞으면 +0.10, 틀리면 −0.05 → set_mastery가 0.0~1.0 잘라내기·둘째 자리 반올림
    current = await store.get_mastery(row.nickname)
    delta = MASTERY_GAIN if correct else -MASTERY_LOSS
    mastery = await store.set_mastery(row.nickname, current + delta)
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
