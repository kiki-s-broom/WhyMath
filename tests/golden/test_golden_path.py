"""골든 패스 e2e — 학생 한 명이 문제 하나를 끝까지 푼다.
이 테스트가 빨간불이면 어떤 PR도 머지하지 않는다."""

import pytest
from fastapi.testclient import TestClient

# golden/api.py에 app이 생기기 전까지는 import 자체가 실패한다 — 그것이 S2의 의도된 빨간불
from golden.api import app

client = TestClient(app)


def test_student_solves_one_problem_end_to_end():
    # GP-1 세션 시작: 닉네임만으로 익명 세션
    r = client.post("/golden/session", json={"nickname": "테스트학생"})
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    # GP-2 문제 제시: 30문항 중 첫 문제
    r = client.get(f"/golden/next?session_id={session_id}")
    assert r.status_code == 200
    problem = r.json()
    assert problem["id"].startswith("LF-")  # 일차함수(Linear Function) 문항 접두사

    # GP-3 + GP-4: 틀린 답을 내면 튜터가 되묻는다 (판정이 아니라 질문이 와야 함)
    r = client.post(
        "/golden/answer",
        json={
            "session_id": session_id,
            "problem_id": problem["id"],
            "text": "모르겠어요",
        },
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "tutor_turn"  # 'graded'가 아니라 'tutor_turn'
    assert len(r.json()["message"]) > 0

    # GP-5 + GP-6: 정답을 내면 판정과 숙련도 갱신이 온다
    r = client.post(
        "/golden/answer",
        json={
            "session_id": session_id,
            "problem_id": problem["id"],
            "text": problem["_test_answer"],  # 테스트 모드에서만 노출되는 정답 필드
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "graded"
    assert body["correct"] is True
    assert 0.0 <= body["mastery"] <= 1.0
    assert body["mastery"] > 0.0  # 맞았으니 0에서 올라가야 한다

    # 다음 문제로 돌아간다 (GP-6 → GP-2 루프)
    r = client.get(f"/golden/next?session_id={session_id}")
    assert r.json()["id"] != problem["id"]

    pytest.fail("S2: 아직 구현 전. 이 줄은 S5에서 지운다.")
