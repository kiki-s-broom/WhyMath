"""S32 T3 연결 — BKT 섀도 기록과 플래그 `GOLDEN_MASTERY_ENGINE`(다섯 걸음 ④ · 인용 F-06).

무엇을 고정하는가
1. 플래그 기본은 simple — 값이 정확히 `bkt`일 때만 bkt다.
2. 판정 1건마다 golden.mastery_shadow에 simple·bkt **2행**이 같은 세션·문제로 쌓인다(완료 기준 ①).
   플래그 값과 무관하다.
3. 기본(simple)에서는 응답 `mastery` = students.mastery = simple 섀도 값(공유 계약 +0.10/−0.05 그대로).
4. bkt 플래그에서는 응답 `mastery`만 bkt 값(둘째 자리 반올림)이고, students.mastery는 여전히 simple이다.
5. bkt는 직전 bkt 섀도 값을 prior로 이어 간다(같은 닉네임 · 새 세션이어도).

튜터는 GOLDEN_FAKE_LLM=1(conftest)이라 실제 LLM을 부르지 않는다.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from golden.api import app
from golden.mastery import BKT_INITIAL, ENGINE_BKT, ENGINE_SIMPLE, FLAG_ENV, response_engine
from golden.mastery.bkt import update
from sqlalchemy import select

from golden import store

client = TestClient(app)


def _nickname(tag: str) -> str:
    """테스트마다 새 닉네임(숙련도·섀도가 이전 실행과 섞이지 않게 · 닉네임 최대 20자 안)."""
    nickname = f"t3{tag[:6]}-{uuid.uuid4().hex[:8]}"
    assert len(nickname) <= 20
    return nickname


def _start(nickname: str) -> str:
    """세션을 시작하고 session_id를 돌려준다."""
    r = client.post("/golden/session", json={"nickname": nickname})
    assert r.status_code == 200
    return str(r.json()["session_id"])


def _answer_current(session_id: str, *, correct: bool) -> dict[str, Any]:
    """지금 문제에 정답(첫 시도 판정) 또는 오답 4번(되묻기 3턴 + 마지막 오답 판정)을 낸다."""
    problem = client.get(f"/golden/next?session_id={session_id}").json()
    texts = [problem["_test_answer"]] if correct else ["999999"] * 4
    body: dict[str, Any] = {}
    for text in texts:
        r = client.post(
            "/golden/answer",
            json={"session_id": session_id, "problem_id": problem["id"], "text": text},
        )
        assert r.status_code == 200
        body = r.json()
    assert body["kind"] == "graded"
    assert body["correct"] is correct
    body["problem_id"] = problem["id"]
    return body


async def _shadow_rows(nickname: str) -> list[tuple[str, float, uuid.UUID, str]]:
    """이 학생의 섀도 행(기록 순서) — (engine, mastery, session_id, problem_id)."""
    await store.ensure_schema()
    async with store._engine().connect() as conn:
        rows = (
            await conn.execute(
                select(
                    store.mastery_shadow.c.engine,
                    store.mastery_shadow.c.mastery,
                    store.mastery_shadow.c.session_id,
                    store.mastery_shadow.c.problem_id,
                )
                .where(store.mastery_shadow.c.nickname == nickname)
                .order_by(store.mastery_shadow.c.id)
            )
        ).all()
    return [(str(r.engine), float(r.mastery), r.session_id, str(r.problem_id)) for r in rows]


# ── 1. 플래그 ──────────────────────────────────────────────────────────────────


def test_flag_defaults_to_simple(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본 simple — 정확히 `bkt`일 때만 bkt. 오타·대문자·공백은 simple로 떨어진다."""
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert response_engine() == ENGINE_SIMPLE
    for value in ("", "simple", "BKT", " bkt", "bkt ", "1"):
        monkeypatch.setenv(FLAG_ENV, value)
        assert response_engine() == ENGINE_SIMPLE, value
    monkeypatch.setenv(FLAG_ENV, "bkt")
    assert response_engine() == ENGINE_BKT


# ── 2·3·4. 한 세션 2행 · 응답 값 ────────────────────────────────────────────────


@pytest.mark.parametrize("flag", [None, "simple", "bkt"], ids=["unset", "simple", "bkt"])
def test_one_graded_answer_writes_two_shadow_rows(
    monkeypatch: pytest.MonkeyPatch, flag: str | None
) -> None:
    """판정 1건 → 같은 세션·문제로 simple·bkt 2행. 플래그가 무엇이든 같다(완료 기준 ①)."""
    if flag is None:
        monkeypatch.delenv(FLAG_ENV, raising=False)
    else:
        monkeypatch.setenv(FLAG_ENV, flag)
    nickname = _nickname(flag or "unset")
    session_id = _start(nickname)
    body = _answer_current(session_id, correct=True)

    rows = asyncio.run(_shadow_rows(nickname))
    assert [r[0] for r in rows] == [ENGINE_SIMPLE, ENGINE_BKT]
    assert {r[2] for r in rows} == {uuid.UUID(session_id)}
    assert {r[3] for r in rows} == {body["problem_id"]}
    simple_value, bkt_value = rows[0][1], rows[1][1]
    assert simple_value == pytest.approx(0.10)  # 새 학생 0.0 + 0.10(공유 계약)
    assert bkt_value == pytest.approx(update(BKT_INITIAL, True), abs=1e-12)  # 0.2에서 시작

    # students.mastery는 플래그와 무관하게 simple 값이다(계약 불변)
    assert asyncio.run(store.get_mastery(nickname)) == pytest.approx(simple_value)
    if flag == "bkt":
        assert body["mastery"] == round(bkt_value, 2)
    else:
        assert body["mastery"] == simple_value


def test_wrong_answer_rows_follow_each_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """마지막 오답 판정도 2행 — simple은 0에서 더 내려가지 않고, bkt는 0.2에서 오답 갱신."""
    monkeypatch.delenv(FLAG_ENV, raising=False)
    nickname = _nickname("wrong")
    body = _answer_current(_start(nickname), correct=False)
    rows = asyncio.run(_shadow_rows(nickname))
    assert [(r[0], r[1]) for r in rows] == [
        (ENGINE_SIMPLE, pytest.approx(0.0)),
        (ENGINE_BKT, pytest.approx(update(BKT_INITIAL, False), abs=1e-12)),
    ]
    assert body["mastery"] == 0.0


# ── 5. bkt prior 이어 가기 ─────────────────────────────────────────────────────


def test_bkt_prior_carries_over_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 닉네임의 새 세션에서도 bkt는 직전 bkt 섀도 값을 prior로 쓴다(simple이 students를 잇듯)."""
    monkeypatch.setenv(FLAG_ENV, "bkt")
    nickname = _nickname("carry")
    first = _answer_current(_start(nickname), correct=True)
    second = _answer_current(_start(nickname), correct=False)

    rows = asyncio.run(_shadow_rows(nickname))
    assert [r[0] for r in rows] == [ENGINE_SIMPLE, ENGINE_BKT] * 2
    expected_1 = update(BKT_INITIAL, True)
    expected_2 = update(expected_1, False)
    assert rows[1][1] == pytest.approx(expected_1, abs=1e-12)
    assert rows[3][1] == pytest.approx(expected_2, abs=1e-12)
    assert [first["mastery"], second["mastery"]] == [round(expected_1, 2), round(expected_2, 2)]
    # simple은 0.10 → 0.05(계약 그대로) — students에만 반영
    assert [rows[0][1], rows[2][1]] == [pytest.approx(0.10), pytest.approx(0.05)]
    assert asyncio.run(store.get_mastery(nickname)) == pytest.approx(0.05)


def test_response_identical_except_mastery_between_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """simple과 bkt 플래그의 판정 응답은 `mastery` 값 말고는 같다(모양 불변 · 화면 계약)."""
    bodies = []
    for flag in ("simple", "bkt"):
        monkeypatch.setenv(FLAG_ENV, flag)
        body = _answer_current(_start(_nickname(f"same-{flag}")), correct=True)
        bodies.append({k: v for k, v in body.items() if k != "mastery"})
        assert isinstance(body["mastery"], float)
    assert bodies[0] == bodies[1]
