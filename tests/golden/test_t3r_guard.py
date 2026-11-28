"""S32R T3R 연결 — 튜터 응답 유출 검사 + 플래그 `GOLDEN_T3R_LEAK_GUARD`(다섯 걸음 ④ · 인용 F-07).

무엇을 고정하는가(지시서 S32R 할 일 3)
1. 플래그 0(기본)에서 튜터 동작이 S32R 이전과 같다 — LLM 1회 · 응답 그대로 · `guard` 없음 · eval_log 0행.
2. 플래그 1에서 ⓐ(튜터가 정답을 새로 말함)는 막는다 — 한 번 다시 만들고, 그래도 걸리면 고정 문장.
3. 플래그 1에서 ⓑ(학생 값 되짚음)·ⓒ(부호 반대 오답 되짚음)는 막지 않는다 — S31R 실제 29턴 전부.
4. 다시 만들기는 1회가 상한이고, 지연 상한(30초)에 걸리면 다시 만들지 않는다.
5. 바꾼 사실은 golden.eval_log에 남는다(문장 없이 축·처리만).

튜터는 GOLDEN_FAKE_LLM=1(conftest)이거나 `_ask_once`를 바꿔 끼운 가짜다 — 실제 LLM을 부르지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from golden.api import app
from golden.eval.leak_guard import (
    FIXED_SENTENCE,
    FLAG_ENV,
    GUARD_VERSION,
    check_reply,
    leak_guard_enabled,
)
from golden.eval.value_exposure import scan_value_exposure
from golden.problems import Problem, load_problems
from golden.store import TurnRow
from golden.tutor import TutorReply
from sqlalchemy import select

from golden import store, tutor

client = TestClient(app)

_CASES = Path(__file__).resolve().parents[2] / "golden" / "data" / "t3r_leak_turns_lf.json"
_REAL: list[dict[str, Any]] = json.loads(_CASES.read_text(encoding="utf-8"))["rows"]
_PROBLEMS: dict[str, Problem] = {p["id"]: p for p in load_problems()}

# ⓐ 합성 사례 — 실제 기록에는 0건(S31R) · (정답, 튜터 문장, 이번 문제의 학생 입력)
_NEW_LEAKS: list[tuple[str, str, list[str]]] = [
    ("16", "x 자리에 5를 넣으면 3×5+1 = 16이니까 답은 16이에요.", ["모르겠어요"]),
    ("4", "6*2-8을 계산하면 무엇이 나오는지 말해 볼래요?", ["-4요?"]),  # 1글자 정답 — 값 축
    ("11", "정답은 11이에요.", ["-11 같아요"]),  # 학생은 부호 반대 오답 — 정답은 튜터가 처음 말함
    ("-12", "f(5) = -12가 돼요.", ["f(5)는 -15예요?"]),
    ("2/3", "기울기는 2/3이에요.", ["-2/3이요?"]),
    # golden-reviewer L1·L2 — 괄호·쉼표를 지워 되짚기로 잘못 읽던 자리, 빼기(이항) 뒤의 양수 정답
    ("12", "정답은 12예요.", ["(1, 2)를 지나요?"]),
    ("11", "x에 2를 넣으면 5-11이 되나요?", ["몰라요"]),
    # 1글자 정답 — 함수 인자·계수 자리의 수는 학생이 그 값을 낸 것이 아니다
    ("3", "6-3을 계산해 볼래요?", ["f(3)이요?"]),
    ("3", "6-3을 계산해 볼래요?", ["3x요?"]),
]


# ── 1. 검사 함수(순수) ────────────────────────────────────────────────────────────


def test_flag_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """플래그는 값이 정확히 `1`일 때만 켜진다."""
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert leak_guard_enabled() is False
    for value in ("0", "", "true", "yes", " 1"):
        monkeypatch.setenv(FLAG_ENV, value)
        assert leak_guard_enabled() is False, value
    monkeypatch.setenv(FLAG_ENV, "1")
    assert leak_guard_enabled() is True


def test_real_cases_table_shape() -> None:
    """S31R 실제 유출 턴 29개(ⓑ 10 · ⓒ 19) — 공허한 통과 금지."""
    kinds = [r["source_kind"] for r in _REAL]
    assert len(_REAL) == 29
    assert kinds.count("b_echo") == 10
    assert kinds.count("c_sign") == 19
    assert all(r["problem_id"] in _PROBLEMS for r in _REAL)
    assert all(_PROBLEMS[r["problem_id"]]["answer"] == r["answer"] for r in _REAL)


@pytest.mark.parametrize(
    "row", _REAL, ids=[f"{r['run']}:{r['problem_id']}:{r['turn']}" for r in _REAL]
)
def test_real_echo_turns_are_not_blocked(row: dict[str, Any]) -> None:
    """ⓑ·ⓒ 실제 29턴은 하나도 막지 않는다. ⓑ는 '드러남 + 학생 되짚기', ⓒ는 '드러나지 않음'이다."""
    check = check_reply(row["tutor"], row["answer"], [row["student"]])
    assert check.new_leak is False
    if row["source_kind"] == "b_echo":
        assert check.axis is not None and check.student_echo is True
    else:
        assert check.axis is None


@pytest.mark.parametrize("answer,reply,students", _NEW_LEAKS, ids=[c[1][:12] for c in _NEW_LEAKS])
def test_new_leaks_are_blocked(answer: str, reply: str, students: list[str]) -> None:
    """ⓐ 합성 사례는 막는다(학생 입력에 그 정답이 없었다)."""
    assert check_reply(reply, answer, students).new_leak is True


def test_reply_parentheses_and_commas_are_not_glued_into_the_answer() -> None:
    """튜터가 `(1, 2)`를 말해도 정답 12가 드러난 것이 아니다(괄호·쉼표를 지워 붙이지 않는다 · L1)."""
    assert check_reply("점 (1, 2)를 지나는지 볼래요?", "12", ["몰라요"]).axis is None
    assert check_reply("점 (-1, 2)를 지나는지 볼래요?", "-12", ["몰라요"]).axis is None


def test_new_leak_becomes_echo_once_student_said_it() -> None:
    """같은 튜터 문장이라도 학생이 앞 턴에 정답 값을 냈으면 되짚기다(앞 턴 포함 · 1글자 정답 포함)."""
    assert check_reply("정답은 11이에요.", "11", ["-11 같아요", "11요?"]).new_leak is False
    assert check_reply("6*2-8을 계산해 볼래요?", "4", ["4요"]).new_leak is False


def test_value_copy_matches_legacy_on_problem_texts() -> None:
    """골든 사본 `scan_value_exposure`가 옛 판과 같은 출력을 낸다 — 30문항 본문·힌트 × 30정답(복사 실재).

    테스트는 옛 모듈을 옛 자리에서 부를 수 있다(골든 코드는 import하지 않는다).
    """
    from whymath_backend.l3.verify_solution import scan_value_exposure as legacy

    texts = [p["stem"] for p in _PROBLEMS.values()] + [p["hint1"] for p in _PROBLEMS.values()]
    texts += [r["tutor"] for r in _REAL] + [c[1] for c in _NEW_LEAKS]
    pairs = 0
    for p in _PROBLEMS.values():
        for text in texts:
            a, b = scan_value_exposure(text, p["answer"]), legacy(text, p["answer"])
            assert (a.outcome.value, a.fragment, a.candidates, a.undecided) == (
                b.outcome.value,
                b.fragment,
                b.candidates,
                b.undecided,
            ), (p["id"], text)
            pairs += 1
    assert pairs >= 30 * 60


# ── 2·3·4. 튜터 연결(가짜 LLM을 바꿔 끼움) ─────────────────────────────────────────


class _ScriptedTutor:
    """`tutor._ask_once` 대역 — 정해 둔 응답을 차례로 내고 몇 번 불렸는지 센다."""

    def __init__(self, *replies: TutorReply) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def __call__(
        self, problem: Problem, history: list[TurnRow], student_text: str, timeout_s: float
    ) -> TutorReply:
        self.calls += 1
        return self.replies[min(self.calls, len(self.replies)) - 1]


def _ask(problem_id: str, student_text: str) -> TutorReply:
    return asyncio.run(tutor.ask(_PROBLEMS[problem_id], [], student_text))


LEAK = TutorReply("x 자리에 5를 넣으면 3×5+1 = 16이니까 답은 16이에요.", False)
CLEAN = TutorReply("x 자리에 5를 넣으면 어떤 식이 되는지 먼저 써 볼래요?", False)


def test_flag_off_keeps_tutor_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """플래그 0: 유출 문장도 그대로 나가고 LLM은 1회 · guard 없음(S32R 이전과 같다)."""
    monkeypatch.delenv(FLAG_ENV, raising=False)
    fake = _ScriptedTutor(LEAK)
    monkeypatch.setattr(tutor, "_ask_once", fake)
    reply = _ask("LF-08", "모르겠어요")
    assert reply == LEAK
    assert reply.guard is None
    assert fake.calls == 1


def test_flag_off_fake_llm_message_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """플래그 0 + 가짜 LLM(conftest): 응답이 S32R 이전 공유 계약 문장 그대로다."""
    monkeypatch.delenv(FLAG_ENV, raising=False)
    reply = _ask("LF-08", "모르겠어요")
    assert reply == TutorReply(tutor.FAKE_PREFIX + _PROBLEMS["LF-08"]["hint1"], False)


def test_flag_on_new_leak_regenerated_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """플래그 1 · ⓐ → 같은 입력으로 1회 다시 만들고, 두 번째가 깨끗하면 그것을 보낸다."""
    monkeypatch.setenv(FLAG_ENV, "1")
    fake = _ScriptedTutor(LEAK, CLEAN)
    monkeypatch.setattr(tutor, "_ask_once", fake)
    reply = _ask("LF-08", "모르겠어요")
    assert reply.message == CLEAN.message
    assert fake.calls == 2
    assert reply.guard == {
        "t3r_guard": GUARD_VERSION,
        "t3r_action": "regenerated",
        "t3r_axis": "glyph",
        "t3r_student_echo": False,
        "t3r_second_axis": None,
    }


def test_flag_on_second_leak_replaced_with_fixed_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    """플래그 1 · 두 번째도 ⓐ → 고정 문장. 다시 만들기는 1회가 상한이다(LLM 2회)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    fake = _ScriptedTutor(LEAK, LEAK, CLEAN)
    monkeypatch.setattr(tutor, "_ask_once", fake)
    reply = _ask("LF-08", "모르겠어요")
    assert reply.message == FIXED_SENTENCE
    assert reply.degraded is False
    assert fake.calls == 2
    assert reply.guard is not None and reply.guard["t3r_action"] == "replaced"


@pytest.mark.parametrize(
    "row", [r for r in _REAL if r["turn"] == 1][:4], ids=lambda r: r["problem_id"]
)
def test_flag_on_echo_passes_with_one_call(
    monkeypatch: pytest.MonkeyPatch, row: dict[str, Any]
) -> None:
    """플래그 1 · ⓑ·ⓒ 실제 문장 → 그대로 보낸다(LLM 1회 · 처리 pass)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    original = TutorReply(row["tutor"], False)
    fake = _ScriptedTutor(original, CLEAN)
    monkeypatch.setattr(tutor, "_ask_once", fake)
    reply = _ask(row["problem_id"], row["student"])
    assert reply.message == row["tutor"]
    assert fake.calls == 1
    assert reply.guard is not None and reply.guard["t3r_action"] == "pass"


def test_flag_on_echo_from_earlier_turn_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """앞 턴 학생 입력도 되짚기 근거다(history)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    fake = _ScriptedTutor(TutorReply("아까 16이라고 했죠. 어떻게 구했는지 말해 볼래요?", False))
    monkeypatch.setattr(tutor, "_ask_once", fake)
    history = [
        TurnRow(turn_no=1, student_text="16이요?", tutor_text="어떻게 구했어요?", kind="tutor_turn")
    ]
    reply = asyncio.run(tutor.ask(_PROBLEMS["LF-08"], history, "모르겠어요"))
    assert fake.calls == 1
    assert reply.guard is not None and reply.guard["t3r_action"] == "pass"
    assert reply.guard["t3r_student_echo"] is True


def test_flag_on_no_time_left_replaces_without_regenerating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """지연 상한(30초)에 가까우면 다시 만들지 않고 고정 문장으로만 바꾼다(LLM 1회)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    fake = _ScriptedTutor(LEAK, CLEAN)
    monkeypatch.setattr(tutor, "_ask_once", fake)
    clock = iter([100.0, 100.0 + tutor.LEAK_GUARD_WAIT_S - 1.0])
    monkeypatch.setattr(tutor, "_now", lambda: next(clock))
    reply = _ask("LF-08", "모르겠어요")
    assert reply.message == FIXED_SENTENCE
    assert fake.calls == 1
    assert reply.guard is not None and reply.guard["t3r_action"] == "replaced_no_time"


def test_flag_on_regen_gets_remaining_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """다시 만들기의 제한 시간은 남은 시간 이하다(학생 대기 30초 상한)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    seen: list[float] = []

    async def fake(
        problem: Problem, history: list[TurnRow], text: str, timeout_s: float
    ) -> TutorReply:
        seen.append(timeout_s)
        return LEAK if len(seen) == 1 else CLEAN

    monkeypatch.setattr(tutor, "_ask_once", fake)
    clock = iter([100.0, 118.0])  # 첫 호출에 18초 — 남은 시간 12초
    monkeypatch.setattr(tutor, "_now", lambda: next(clock))
    _ask("LF-08", "모르겠어요")
    assert seen == [tutor.LLM_TIMEOUT_S, pytest.approx(12.0)]


def test_flag_on_regen_degraded_uses_fixed_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    """다시 만들기가 실패(대체 문장)하면 고정 문장으로 바꾼다 — 유출 문장을 내보내지 않는다."""
    monkeypatch.setenv(FLAG_ENV, "1")
    fake = _ScriptedTutor(LEAK, TutorReply("대체 문장", True))
    monkeypatch.setattr(tutor, "_ask_once", fake)
    reply = _ask("LF-08", "모르겠어요")
    assert reply.message == FIXED_SENTENCE
    assert reply.guard is not None and reply.guard["t3r_action"] == "replaced_regen_failed"


def test_flag_on_degraded_first_reply_is_not_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """첫 응답이 대체 문장(degraded)이면 검사하지 않고 그대로 보낸다(처리 skipped_degraded)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    degraded = TutorReply("대체 문장 16", True)
    fake = _ScriptedTutor(degraded)
    monkeypatch.setattr(tutor, "_ask_once", fake)
    reply = _ask("LF-08", "모르겠어요")
    assert (reply.message, reply.degraded) == (degraded.message, True)
    assert fake.calls == 1
    assert reply.guard is not None and reply.guard["t3r_action"] == "skipped_degraded"


# ── 5. eval_log 기록(골든 패스 한 바퀴) ─────────────────────────────────────────────


async def _eval_rows(session_id: str) -> list[dict[str, Any]]:
    """세션의 tutor_turn 턴들에 붙은 eval_log 행(턴 순서)."""
    await store.ensure_schema()
    async with store._engine().connect() as conn:
        rows = (
            await conn.execute(
                select(store.eval_log.c.verdict_json)
                .join(store.turns, store.turns.c.id == store.eval_log.c.turn_id)
                .where(
                    store.turns.c.session_id == uuid.UUID(session_id),
                    store.turns.c.kind == "tutor_turn",
                )
                .order_by(store.turns.c.id)
            )
        ).all()
    return [dict(r.verdict_json) for r in rows]


@pytest.mark.parametrize("flag", ["0", "1"])
def test_golden_path_records_guard_only_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """한 바퀴(오답 → 되묻기 → 정답)가 두 상태 모두 초록. 켜짐이면 되묻기 턴에 T3R 기록 1건, 꺼짐이면 0건.

    가짜 튜터가 정답을 새로 말한다 — 켜짐이면 학생 응답이 고정 문장으로 바뀐다.
    """
    monkeypatch.setenv(FLAG_ENV, flag)
    monkeypatch.setattr(tutor, "_ask_once", _ScriptedTutor(TutorReply("답은 16이에요.", False)))
    r = client.post("/golden/session", json={"nickname": f"t3r-{flag}-{uuid.uuid4().hex[:6]}"})
    session_id = r.json()["session_id"]
    bodies = []
    for text in ("모르겠어요", "16"):
        r = client.post(
            "/golden/answer", json={"session_id": session_id, "problem_id": "LF-08", "text": text}
        )
        assert r.status_code == 200
        bodies.append(r.json())
    assert [b["kind"] for b in bodies] == ["tutor_turn", "graded"]
    assert set(bodies[0]) == {"kind", "message", "turn"}  # 응답 모양은 플래그와 무관
    rows = [row for row in asyncio.run(_eval_rows(session_id)) if "t3r_guard" in row]
    if flag == "1":
        assert bodies[0]["message"] == FIXED_SENTENCE
        assert len(rows) == 1
        assert rows[0]["t3r_action"] == "replaced"
        assert "답은" not in json.dumps(rows[0], ensure_ascii=False)  # 문장은 담지 않는다
    else:
        assert bodies[0]["message"] == "답은 16이에요."
        assert rows == []
