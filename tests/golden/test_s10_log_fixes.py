"""S10 로그 수정 재현 테스트 — S9(본인 self-*)·S11(AI 시뮬레이션 sim-*) 로그가 가리킨 문제만 다룬다.

항목마다 "어느 로그의 몇 행"에서 나왔는지 적는다. 줄 번호는 각 turns CSV의 줄 번호(머리줄 = 1행)다.
- S9 로그: Kiki 머신 golden/logs/self1_turns.csv(16행) — 줄 번호는 S9 보고에 있다.
- S11 로그: golden/reports_no_students/S11/sim_<페르소나>[_r2]_turns.csv.

DB가 필요한 테스트는 실제 PostgreSQL(WHYMATH_DATABASE_URL)을 쓴다. LLM은 부르지 않는다.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from golden.api import app

from golden import api

client = TestClient(app)


# ── 항목 1: 판정 문장 조사 오류("답은 8였어요") ────────────────────────────────
# S9 17행 "이번 문제의 답은 8였어요"(LF-05) ·
# S11 sim_no-setup 21행 "답은 8였어요"·33행 "16였어요"·5행 "-12였어요"(이 줄은 맞는 조사) 등.
# 받침이 있는 수(1·3·6·7·8·0·10·16…) 뒤에는 "이었어요", 받침이 없는 수(2·4·5·9) 뒤에는 "였어요".
@pytest.mark.parametrize(
    ("answer", "expected_tail"),
    [
        ("8", "8이었어요"),  # S9 17행 · S11 no-setup 21행
        ("16", "16이었어요"),  # S11 no-setup 33행 · slope-blind 27행
        ("1", "1이었어요"),  # S11 no-setup 9행
        ("0", "0이었어요"),  # S11 no-setup 25행
        ("11", "11이었어요"),  # S11 no-setup 29행
        ("-8", "-8이었어요"),  # S11 no-setup 17행
        ("-11", "-11이었어요"),  # S11 no-setup 41행
        ("-12", "-12였어요"),  # S11 no-setup 5행(원래 맞던 조사 — 바뀌면 안 된다)
        ("4", "4였어요"),  # S11 no-setup 13행(원래 맞던 조사)
        ("-4", "-4였어요"),  # S11 no-setup 37행(원래 맞던 조사)
        ("15", "15였어요"),  # 문항 LF-16(받침 없음 · 오)
        ("30", "30이었어요"),  # 끝자리 0은 "십"이라 받침 있음
        ("-3/2", "-3/2이었어요"),  # LF-14 "이분의 삼" — 분자로 끝난다
        ("2/3", "2/3였어요"),  # LF-15 "삼분의 이"
        ("2*x + 1", "2*x + 1이었어요"),  # LF-23 식 정답
        ("-3*x + 5", "-3*x + 5였어요"),  # LF-22 식 정답
    ],
)
def test_wrong_feedback_particle_follows_final_sound(answer: str, expected_tail: str) -> None:
    feedback = api.wrong_feedback(answer)
    assert feedback == f"이번 문제의 답은 {expected_tail}. 다음 문제에서 다시 해 봐요."


def _answer(session_id: str, problem_id: str, text: str) -> dict[str, object]:
    r = client.post(
        "/golden/answer",
        json={"session_id": session_id, "problem_id": problem_id, "text": text},
    )
    assert r.status_code == 200
    body: dict[str, object] = r.json()
    return body


def test_s9_line17_lf05_wrong_feedback_says_8_ieosseoyo() -> None:
    """S9 17행 재생 — LF-05(정답 8)를 3턴 동안 틀리고 4번째도 틀리면 판정 문장의 조사가 맞아야 한다.

    S9 입력 그대로: 14행 `12` → 15행 `4요?` → 16행 `0이요?` → 17행 `0`.
    """
    nickname = "t-" + uuid.uuid4().hex[:12]
    session_id = client.post("/golden/session", json={"nickname": nickname}).json()["session_id"]
    # LF-01~LF-04는 정답으로 넘긴다(cursor를 LF-05까지 옮기기 위해)
    for _ in range(4):
        problem = client.get(f"/golden/next?session_id={session_id}").json()
        assert _answer(session_id, problem["id"], problem["_test_answer"])["correct"] is True
    problem = client.get(f"/golden/next?session_id={session_id}").json()
    assert problem["id"] == "LF-05"

    for text in ("12", "4요?", "0이요?"):
        assert _answer(session_id, "LF-05", text)["kind"] == "tutor_turn"
    body = _answer(session_id, "LF-05", "0")
    assert body["kind"] == "graded"
    assert body["correct"] is False
    assert body["feedback"] == "이번 문제의 답은 8이었어요. 다음 문제에서 다시 해 봐요."
