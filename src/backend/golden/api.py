"""골든 패스 HTTP 엔드포인트 3개(session · next · answer, 접두 /golden) — S4가 채운다.

서버: `uvicorn golden.api:app`. 옛 `create_app`에는 등록하지 않는다(파사드 분리 — 옛 앱은 그대로).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from golden import grade, problems, store, tutor
from golden.eval import (
    T2_MATCHER_VERSION,
    evaluate_tutor_reply,
    match_misconception,
    misconception_description,
    misconception_enabled,
    rubric_enabled,
)

logger = logging.getLogger(__name__)

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
        # S28 T2(GOLDEN_T2_MISCONCEPTION=1일 때만): 튜터를 부르기 전에 매칭해, 매칭이 있으면
        # 그 오개념 한 줄 설명을 튜터 사용자 프롬프트에 넣는다. 꺼져 있으면 매칭도 하지 않는다.
        t2 = _t2_match(problem, body.text) if misconception_enabled() else None
        hint = t2.description if t2 is not None else None
        reply = await tutor.ask(problem, history, body.text, misconception=hint)
        turn_no = turns_used + 1
        turn_id = await store.record_turn(
            session_id=row.session_id,
            problem_id=problem["id"],
            turn_no=turn_no,
            student_text=body.text,
            tutor_text=reply.message,
            kind="tutor_turn",
            correct=False,
        )
        if rubric_enabled():
            # S22 T1(GOLDEN_T1_RUBRIC=1일 때만): 평가는 기록만 한다
            # — 아래 응답은 한 글자도 바꾸지 않는다
            await _record_t1_eval(turn_id, problem, body.text, reply.message)
        if t2 is not None:
            # S27 T2 기록(+ S28: 프롬프트에 넣었는지) — 응답은 튜터 문장 그대로
            await _record_t2(turn_id, problem, t2, in_prompt=hint is not None)
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


async def _record_t1_eval(
    turn_id: int, problem: problems.Problem, student_text: str, message: str
) -> None:
    """T1 평가기로 튜터 되묻기를 재고 golden.eval_log에 남긴다(S22 · 다섯 걸음 ④ · 기록 전용).

    - 유출(leak) 판정이면 경고 로그를 남긴다. 로그에는 문제 ID·턴 id·유출 출처만 적고
      튜터·학생 문장은 적지 않는다(미성년자 대화 원문을 로그로 흘리지 않는다).
    - 평가나 기록이 **어떤 이유로든** 실패해도 학생 응답은 그대로 나간다(평가는 부가 기록이다).
      이 함수 앞에서 튜터 턴이 이미 기록됐으므로, 여기서 오류가 올라가면 학생은 응답 없이
      되묻기 기회(3번 중 1번)를 잃는다. 그래서 넓게 잡되 예외 타입명을 경고 로그에 남긴다
      (CLAUDE.md 침묵 실패 금지 · Kiki 결정 2026-11-20 · RS-G2 허용 목록 1줄).
      빠진 건수는 eval_log 행 수와 tutor_turn 수를 대조하면 숫자로 보인다.
    """
    try:
        verdict = evaluate_tutor_reply(
            message, problem["answer"], student_text=student_text, problem_text=problem["stem"]
        )
        if verdict.leak:
            logger.warning(
                "golden T1 평가: 정답 유출 판정 — problem=%s turn_id=%s origin=%s",
                problem["id"],
                turn_id,
                verdict.leak_origin,
            )
        await store.record_eval(turn_id, verdict.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001 — Kiki 승인 2026-11-20(평가가 응답을 막지 않게)
        logger.warning(
            "golden T1 평가 실패 — 응답은 그대로 보냄: problem=%s turn_id=%s %s",
            problem["id"],
            turn_id,
            type(exc).__name__,
        )


@dataclass(frozen=True)
class _T2Match:
    """T2 매칭 1회 결과 — 오개념 ID(없으면 None)와 튜터에 넣을 한 줄 설명(없으면 None)."""

    mis_id: str | None
    description: str | None


def _t2_match(problem: problems.Problem, student_text: str) -> _T2Match | None:
    """틀린 답 → 오개념 ID + 한 줄 설명(S27 매칭 · S28 설명). 실패하면 None.

    - 매칭 결과가 None이어도 `_T2Match(None, None)`을 돌려준다 — "매칭 없음"도 기록한다.
    - 실패(None 반환)면 튜터에 아무것도 넣지 않고 기록도 하지 않는다. 학생 응답은 그대로 나간다.
      잡는 예외는 표 파일 오류(`OSError`·`ValueError`·`KeyError`)로 좁힌다 — 넓은 `except`는
      허용 목록과 Kiki 승인이 필요해 쓰지 않았다(S27과 같은 처리). 그 밖의 예외는 올라간다.
      경고 로그에는 문제 ID·예외 타입명만 적고 학생 문장은 적지 않는다.
    """
    try:
        mis_id = match_misconception(problem, student_text)
        description = misconception_description(mis_id) if mis_id is not None else None
    except (OSError, ValueError, KeyError) as exc:
        logger.warning(
            "golden T2 매칭 실패 — 응답은 그대로 보냄: 단계=매칭 problem=%s %s",
            problem["id"],
            type(exc).__name__,
        )
        return None
    return _T2Match(mis_id=mis_id, description=description)


async def _record_t2(
    turn_id: int, problem: problems.Problem, match: _T2Match, *, in_prompt: bool
) -> None:
    """T2 매칭 결과를 golden.eval_log의 그 턴 행에 남긴다(S27 · S28이 `t2_prompt_hint`를 더함).

    `t2_prompt_hint`는 이 턴의 튜터 프롬프트에 오개념 한 줄을 넣었는지다(판정 턴은 늘 False —
    튜터를 부르지 않는다). 기록이 DB·연결 오류(`SQLAlchemyError`·`OSError`)로 실패해도 응답은
    그대로 나가고, 경고 로그에 문제 ID·턴 id·예외 타입명만 남긴다.
    """
    try:
        await store.record_eval(
            turn_id,
            {
                "t2_matcher": T2_MATCHER_VERSION,
                "t2_misconception_id": match.mis_id,
                "t2_prompt_hint": in_prompt,
            },
        )
    except (SQLAlchemyError, OSError) as exc:
        logger.warning(
            "golden T2 매칭 실패 — 응답은 그대로 보냄: 단계=기록 problem=%s turn_id=%s %s",
            problem["id"],
            turn_id,
            type(exc).__name__,
        )


async def _graded(
    row: store.SessionRow,
    problem: problems.Problem,
    student_text: str,
    correct: bool,
    turns_used: int,
    feedback: str,
) -> dict[str, object]:
    """판정 응답 — 턴 기록 → 숙련도 갱신 → 지금 보던 문제라면 cursor를 다음 문제로 옮긴다."""
    turn_id = await store.record_turn(
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
    if not correct and misconception_enabled():
        # S27 T2(플래그 켜짐 · 3턴을 다 쓴 마지막 오답): 기록만 한다 — 응답 불변.
        # cursor·숙련도 갱신 뒤에 부른다 — 좁은 except 밖의 예외가 나도 판정 상태가 반쯤 남지 않게.
        t2 = _t2_match(problem, student_text)
        if t2 is not None:
            await _record_t2(turn_id, problem, t2, in_prompt=False)
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
