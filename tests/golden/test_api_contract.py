"""골든 패스 HTTP 계약 3개(session · next · answer) — 응답 모양이 공유 계약과 같은지 본다.

실제 PostgreSQL(WHYMATH_DATABASE_URL)에 golden 스키마를 만들어 쓴다. LLM은 부르지 않는다
(conftest가 GOLDEN_FAKE_LLM=1을 켠다).
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from golden.api import app

client = TestClient(app)


def _nickname() -> str:
    """테스트마다 겹치지 않는 닉네임(20자 이하) — 숙련도 이어받기가 다른 테스트에 새지 않게."""
    return "t-" + uuid.uuid4().hex[:12]


def _start() -> str:
    r = client.post("/golden/session", json={"nickname": _nickname()})
    assert r.status_code == 200
    return str(r.json()["session_id"])


def test_session_create_returns_contract_shape() -> None:
    nickname = _nickname()
    r = client.post("/golden/session", json={"nickname": nickname})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"session_id", "nickname", "mastery"}
    assert uuid.UUID(body["session_id"])
    assert body["nickname"] == nickname
    assert body["mastery"] == 0.0


def test_same_nickname_gets_new_session_id() -> None:
    nickname = _nickname()
    first = client.post("/golden/session", json={"nickname": nickname}).json()
    second = client.post("/golden/session", json={"nickname": nickname}).json()
    assert first["session_id"] != second["session_id"]
    assert second["mastery"] == first["mastery"]


@pytest.mark.parametrize("nickname", ["", "가" * 21])
def test_nickname_length_out_of_range_is_422(nickname: str) -> None:
    r = client.post("/golden/session", json={"nickname": nickname})
    assert r.status_code == 422


@pytest.mark.parametrize("session_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_unknown_session_id_is_404(session_id: str) -> None:
    assert client.get(f"/golden/next?session_id={session_id}").status_code == 404
    r = client.post(
        "/golden/answer",
        json={"session_id": session_id, "problem_id": "LF-01", "text": "3"},
    )
    assert r.status_code == 404


def test_unknown_problem_id_is_404() -> None:
    session_id = _start()
    r = client.post(
        "/golden/answer",
        json={"session_id": session_id, "problem_id": "LF-99", "text": "3"},
    )
    assert r.status_code == 404


def test_next_returns_contract_shape_with_test_answer_in_test_mode() -> None:
    session_id = _start()
    r = client.get(f"/golden/next?session_id={session_id}")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "stem", "index", "total", "_test_answer"}
    assert body["id"].startswith("LF-")
    assert body["index"] == 1
    assert body["total"] >= 1


def test_test_answer_absent_without_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOLDEN_TEST_MODE", raising=False)
    session_id = _start()
    body = client.get(f"/golden/next?session_id={session_id}").json()
    assert "_test_answer" not in body
    # 정답·힌트는 평소 절대 내보내지 않는다
    assert set(body) == {"id", "stem", "index", "total"}


def test_three_wrong_answers_then_fourth_is_graded() -> None:
    session_id = _start()
    problem = client.get(f"/golden/next?session_id={session_id}").json()
    payload = {"session_id": session_id, "problem_id": problem["id"], "text": "모르겠어요"}

    for turn in (1, 2, 3):
        r = client.post("/golden/answer", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "tutor_turn"
        assert body["turn"] == turn
        assert len(body["message"]) > 0
        assert "degraded" not in body  # 가짜 LLM은 장애가 아니다

    r = client.post("/golden/answer", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"kind", "correct", "mastery", "turns_used", "feedback"}
    assert body["kind"] == "graded"
    assert body["correct"] is False
    assert body["turns_used"] == 3
    assert 0.0 <= body["mastery"] <= 1.0
    assert problem["_test_answer"] in body["feedback"]  # 3턴 소진 후에는 정답을 알려 준다

    # 판정이 났으니 다음 문제로 넘어간다(문항이 1개뿐이면 순환해 같은 문제)
    after = client.get(f"/golden/next?session_id={session_id}").json()
    assert after["index"] == (problem["index"] % problem["total"]) + 1


def _answer(session_id: str, problem_id: str, text: str) -> dict[str, object]:
    r = client.post(
        "/golden/answer",
        json={"session_id": session_id, "problem_id": problem_id, "text": text},
    )
    assert r.status_code == 200
    body: dict[str, object] = r.json()
    return body


def test_mastery_update_gain_loss_and_clamp() -> None:
    """GP-6 숙련도 갱신 — 새 닉네임(시작 0.0)으로 +0.10·−0.05·0 아래 잘라내기를 정확한 값으로 본다.

    e2e는 `mastery > 0.0`만 보므로, DB에 같은 닉네임이 남아 있으면 갱신을 빼먹어도 통과할 수 있다.
    이 테스트가 그 빈틈을 막는다.
    """
    nickname = _nickname()
    session_id = client.post("/golden/session", json={"nickname": nickname}).json()["session_id"]

    # ① 처음부터 3턴 소진 후 오답 판정 → 0.0 − 0.05 = 0.0 (0 아래로 안 내려감)
    problem = client.get(f"/golden/next?session_id={session_id}").json()
    for _ in range(3):
        assert _answer(session_id, problem["id"], "모르겠어요")["kind"] == "tutor_turn"
    body = _answer(session_id, problem["id"], "모르겠어요")
    assert body["correct"] is False
    assert body["mastery"] == 0.0
    assert (
        body["feedback"]
        == f"이번 문제의 답은 {problem['_test_answer']}였어요. 다음 문제에서 다시 해 봐요."
    )

    # ② 다음 문제 정답 → 0.0 + 0.10 = 0.10
    problem = client.get(f"/golden/next?session_id={session_id}").json()
    body = _answer(session_id, problem["id"], problem["_test_answer"])
    assert body == {
        "kind": "graded",
        "correct": True,
        "mastery": 0.10,
        "turns_used": 0,
        "feedback": "맞았어요. 다음 문제로 가 볼까요?",
    }

    # ③ 다음 문제 3턴 뒤 오답 → 0.10 − 0.05 = 0.05
    problem = client.get(f"/golden/next?session_id={session_id}").json()
    for _ in range(3):
        _answer(session_id, problem["id"], "모르겠어요")
    assert _answer(session_id, problem["id"], "모르겠어요")["mastery"] == 0.05

    # ④ 같은 닉네임으로 새 세션 → 숙련도를 이어받는다(DB에 저장됐다)
    again = client.post("/golden/session", json={"nickname": nickname}).json()
    assert again["mastery"] == 0.05
