"""S22 T1 연결 — 평가기 `golden.eval`과 기능 플래그 `GOLDEN_T1_RUBRIC`(다섯 걸음 ④ · 인용 F-01).

무엇을 고정하는가
1. 평가기 `evaluate_tutor_reply`가 사본 함수의 출력을 그대로 옮기고, 유출 출처(`leak_origin`)를 가린다.
2. 플래그 꺼짐(기본)·켜짐 **두 상태 모두**에서 골든 패스 한 바퀴가 초록이고, 학생이 받는 응답이 같다.
3. 켜짐일 때만 `golden.eval_log`에 턴 1개당 판정 1행이 생긴다. 꺼짐이면 0행이다.
4. 유출 판정 경고 로그에는 문제 ID가 있고 튜터·학생 문장은 없다.
5. 기록 쓰기가 DB 오류로 실패해도 응답은 그대로 나가고, 예외 타입명이 경고 로그에 남는다.

튜터는 GOLDEN_FAKE_LLM=1(conftest)이라 실제 LLM을 부르지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from golden.api import app
from golden.eval import evaluate_tutor_reply, rubric_enabled
from golden.eval.rubric import EVALUATOR_VERSION, FLAG_ENV
from golden.problems import Problem
from golden.store import TurnRow
from golden.tutor import TutorReply
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from golden import api, store, tutor

client = TestClient(app)


# ── 1. 평가기(순수 함수) ──────────────────────────────────────────────────────────


def test_flag_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """플래그 기본값은 끔 — 환경변수가 없거나 `1`이 아니면 꺼져 있다."""
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert rubric_enabled() is False
    for value in ("0", "", "true", "yes", " 1"):
        monkeypatch.setenv(FLAG_ENV, value)
        assert rubric_enabled() is False, value
    monkeypatch.setenv(FLAG_ENV, "1")
    assert rubric_enabled() is True


def test_verdict_mirrors_copied_rubric_fields() -> None:
    """옛 루브릭 출력(S21 특성화 1번 사례)을 그대로 옮긴다 — 유출 · 발문 있음 · 통과 아님."""
    reply = "f(5)는 -12라고 말했군요. 어떤 식을 세웠는지 말해 볼래요?"
    verdict = evaluate_tutor_reply(reply, "-12")
    assert verdict.model_dump(mode="json") == {
        "evaluator": EVALUATOR_VERSION,
        "leak": True,
        "leakage": "leaked",
        "leak_origin": "unknown",  # 학생 답·문제 본문을 주지 않았다
        "passed": False,
        "has_socratic_prompt": True,
        "reasons": [
            "정답 값이 발화에 노출됨 — 최상위 교수학 금기 위반.",
            "소크라테스 발문 신호 존재.",
        ],
    }


# (튜터 문장, 정답, 학생 답, 문제 본문, 기대 leakage, 기대 leak_origin)
_ORIGIN_CASES: list[tuple[str, str, str, str, str, str]] = [
    # 학생이 이미 쓴 값을 되받음 — 정답이지만 앞말 때문에 오답 처리된 경우(F-02 형태)
    (
        "-12라고 했군요. 왜 그렇게 생각했어요?",
        "-12",
        "f(5)는 -12예요.",
        "f(x)=-3x+3 f(5)?",
        "leaked",
        "student_echo",
    ),
    # 문제 식에만 있는 토큰(S21 특성화 2번과 같은 형태)
    (
        "-5x - 4에 0을 넣으면 어떤 식이 돼요?",
        "-4",
        "모르겠어요",
        "f(x)=-5x-4일 때 f(0)",
        "leaked",
        "problem_text",
    ),
    # 학생도 문제도 말하지 않은 정답을 튜터가 새로 말함 — 진짜 유출 후보
    ("답은 -12예요. 이해했어요?", "-12", "15", "f(x)=-3x+3일 때 f(5)", "leaked", "new"),
    # 유출 아님
    ("x 자리에 5를 넣으면 어떻게 돼요?", "-12", "15", "f(x)=-3x+3일 때 f(5)", "clean", "none"),
    # 1글자 정답 — 판정 유보는 유출이 아니다
    ("4라고 했군요. 왜 그렇게 생각했어요?", "4", "4요", "f(2)", "undecidable", "none"),
]


@pytest.mark.parametrize(
    ("reply", "answer", "student", "stem", "leakage", "origin"),
    _ORIGIN_CASES,
    ids=[c[5] + "-" + c[4] for c in _ORIGIN_CASES],
)
def test_leak_origin(
    reply: str, answer: str, student: str, stem: str, leakage: str, origin: str
) -> None:
    """유출 출처 4가지(+유출 아님)를 학생 답·문제 본문으로 가린다. leakage 자체는 옛 탐지기 그대로."""
    verdict = evaluate_tutor_reply(reply, answer, student_text=student, problem_text=stem)
    assert verdict.leakage == leakage
    assert verdict.leak is (leakage == "leaked")
    assert verdict.leak_origin == origin


def test_verdict_is_deterministic() -> None:
    """같은 입력 → 같은 판정(100회)."""
    dumps = {
        repr(
            evaluate_tutor_reply(
                "-12라고 했군요?", "-12", student_text="-12", problem_text="f(5)"
            ).model_dump(mode="json")
        )
        for _ in range(100)
    }
    assert len(dumps) == 1


# ── 2·3. 플래그 0/1 양쪽에서 골든 패스 한 바퀴 ────────────────────────────────────────


@pytest.fixture(params=["0", "1"], ids=["flag-off", "flag-on"])
def t1_flag(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """플래그를 끄고 켠 두 상태로 같은 테스트를 돌린다(값은 요청 처리 시점에 읽힌다)."""
    value: str = request.param
    monkeypatch.setenv(FLAG_ENV, value)
    yield value


async def _eval_rows(turn_ids: list[int]) -> list[Any]:
    """turn_id들에 대한 eval_log 행."""
    await store.ensure_schema()
    async with store._engine().connect() as conn:
        return list(
            (
                await conn.execute(
                    select(store.eval_log.c.turn_id, store.eval_log.c.verdict_json).where(
                        store.eval_log.c.turn_id.in_(turn_ids)
                    )
                )
            ).all()
        )


async def _turn_ids(session_id: str) -> list[int]:
    """세션의 tutor_turn 턴 id들(기록 순서)."""
    async with store._engine().connect() as conn:
        rows = (
            await conn.execute(
                select(store.turns.c.id)
                .where(
                    store.turns.c.session_id == uuid.UUID(session_id),
                    store.turns.c.kind == "tutor_turn",
                )
                .order_by(store.turns.c.id)
            )
        ).all()
    return [int(r.id) for r in rows]


def _run_one_problem(nickname: str) -> tuple[str, list[dict[str, Any]]]:
    """GP-1~GP-6 한 바퀴: 틀린 답 2번(되묻기 2턴) → 정답. 응답 본문들을 돌려준다."""
    r = client.post("/golden/session", json={"nickname": nickname})
    assert r.status_code == 200
    session_id = r.json()["session_id"]
    problem = client.get(f"/golden/next?session_id={session_id}").json()
    bodies = []
    for text in ("모르겠어요", "999999", problem["_test_answer"]):
        r = client.post(
            "/golden/answer",
            json={"session_id": session_id, "problem_id": problem["id"], "text": text},
        )
        assert r.status_code == 200
        bodies.append(r.json())
    assert [b["kind"] for b in bodies] == ["tutor_turn", "tutor_turn", "graded"]
    assert bodies[-1]["correct"] is True
    return session_id, bodies


def test_golden_path_green_and_eval_log_only_when_flag_on(t1_flag: str) -> None:
    """두 플래그 상태 모두 한 바퀴가 초록. 켜짐이면 되묻기 턴마다 eval_log 1행, 꺼짐이면 0행."""
    session_id, bodies = _run_one_problem(f"t1-{t1_flag}-{uuid.uuid4().hex[:6]}")
    turn_ids = asyncio.run(_turn_ids(session_id))
    assert len(turn_ids) == 2
    rows = asyncio.run(_eval_rows(turn_ids))
    if t1_flag == "1":
        assert sorted(r.turn_id for r in rows) == turn_ids
        for row in rows:
            assert row.verdict_json["evaluator"] == EVALUATOR_VERSION
            assert row.verdict_json["leakage"] in {"leaked", "clean", "undecidable"}
            assert set(row.verdict_json) == {
                "evaluator",
                "leak",
                "leakage",
                "leak_origin",
                "passed",
                "has_socratic_prompt",
                "reasons",
            }
    else:
        assert rows == []
    # 학생이 받는 응답 모양은 플래그와 무관하다(평가 칸이 새어 나가지 않는다)
    assert set(bodies[0]) == {"kind", "message", "turn"}


def test_response_identical_with_flag_off_and_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 입력이면 플래그 0과 1의 학생 응답이 한 글자도 다르지 않다(평가는 기록만)."""
    results = {}
    for value in ("0", "1"):
        monkeypatch.setenv(FLAG_ENV, value)
        _, bodies = _run_one_problem(f"t1-same-{value}-{uuid.uuid4().hex[:6]}")
        # 숙련도는 닉네임마다 새로 시작하므로 같은 값이다
        results[value] = bodies
    assert results["0"] == results["1"]


# ── 4·5. 경고 로그와 기록 실패 ────────────────────────────────────────────────────────


def _leaking_ask(answer_holder: dict[str, str]) -> Any:
    """정답을 그대로 말하는 가짜 튜터(유출 경로를 일부러 만든다)."""

    async def _ask(
        problem: Problem,
        history: list[TurnRow],
        student_text: str,
        misconception: str | None = None,
    ) -> TutorReply:
        answer_holder["answer"] = problem["answer"]
        return TutorReply(
            message=f"비밀 문장 답은 {problem['answer']} 이에요. 알겠어요?", degraded=False
        )

    return _ask


def test_leak_warning_logs_problem_id_not_sentences(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """유출 판정이면 경고 1건 — 문제 ID·출처는 있고 튜터·학생 문장은 없다. 응답은 그대로."""
    monkeypatch.setenv(FLAG_ENV, "1")
    holder: dict[str, str] = {}
    monkeypatch.setattr(tutor, "ask", _leaking_ask(holder))
    r = client.post("/golden/session", json={"nickname": f"t1-leak-{uuid.uuid4().hex[:6]}"})
    session_id = r.json()["session_id"]
    # LF-01(정답 -12 · 2글자 이상이라 옛 탐지기가 판정을 유보하지 않는다)을 직접 고른다
    problem = {"id": "LF-01"}
    student_text = "학생비밀문장"
    with caplog.at_level(logging.WARNING, logger=api.__name__):
        r = client.post(
            "/golden/answer",
            json={"session_id": session_id, "problem_id": problem["id"], "text": student_text},
        )
    assert r.status_code == 200
    assert r.json()["message"].startswith("비밀 문장 답은")  # 응답은 바뀌지 않았다
    assert holder["answer"] == "-12"  # 가짜 튜터가 정말 불렸다(주입 실재)
    warnings = [rec for rec in caplog.records if "정답 유출 판정" in rec.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert f"problem={problem['id']}" in message
    assert "origin=new" in message
    assert "비밀 문장" not in message and student_text not in message


class _InjectedEvalBugError(RuntimeError):
    """평가기 버그를 흉내 내는 주입 예외(타입명이 로그에 남는지 보려고 고유한 이름을 쓴다)."""


async def _record_raises_db(turn_id: int, verdict: dict[str, object]) -> None:
    raise OperationalError("INSERT", {}, Exception("주입한 실패"))


async def _record_raises_os(turn_id: int, verdict: dict[str, object]) -> None:
    # SQLAlchemy가 감싸지 않는 연결 단계 오류(리뷰 지적 — 예전 좁은 except는 못 잡았다)
    raise ConnectionRefusedError("주입한 연결 실패")


def _evaluator_raises(*args: object, **kwargs: object) -> object:
    raise _InjectedEvalBugError("주입한 평가기 버그")


# (주입 지점 이름, 대체 함수, 로그에 남아야 할 예외 타입명)
_FAILURES: list[tuple[str, Any, str]] = [
    ("record_eval", _record_raises_db, "OperationalError"),
    ("record_eval", _record_raises_os, "ConnectionRefusedError"),
    ("evaluate_tutor_reply", _evaluator_raises, "_InjectedEvalBugError"),
]


@pytest.mark.parametrize(
    ("target", "replacement", "type_name"), _FAILURES, ids=[f[2] for f in _FAILURES]
)
def test_eval_failure_keeps_response(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    target: str,
    replacement: Any,
    type_name: str,
) -> None:
    """평가·기록이 어떤 이유로 실패해도 응답은 200 그대로 · 경고에 예외 타입명(Kiki 결정 2026-11-20).

    DB 오류(SQLAlchemy) · 연결 오류(SQLAlchemy 밖) · 평가기 자체 버그 세 가지를 주입한다.
    튜터 턴은 평가 전에 이미 기록되므로, 여기서 500이 나면 학생이 되묻기 기회를 잃는다.
    """
    monkeypatch.setenv(FLAG_ENV, "1")
    if target == "record_eval":
        monkeypatch.setattr(store, "record_eval", replacement)
    else:
        monkeypatch.setattr(api, "evaluate_tutor_reply", replacement)
    r = client.post("/golden/session", json={"nickname": f"t1-fail-{uuid.uuid4().hex[:6]}"})
    session_id = r.json()["session_id"]
    problem = client.get(f"/golden/next?session_id={session_id}").json()
    student_text = "학생비밀문장"
    with caplog.at_level(logging.WARNING, logger=api.__name__):
        r = client.post(
            "/golden/answer",
            json={"session_id": session_id, "problem_id": problem["id"], "text": student_text},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "tutor_turn" and body["turn"] == 1
    failures = [rec for rec in caplog.records if "golden T1 평가 실패" in rec.getMessage()]
    assert len(failures) == 1  # 주입이 실제로 실패 경로를 밟았다(조용히 성공하지 않았다)
    message = failures[0].getMessage()
    assert type_name in message
    assert f"problem={problem['id']}" in message
    assert student_text not in message and body["message"] not in message
