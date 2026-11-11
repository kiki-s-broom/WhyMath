"""S11 AI 시뮬레이션 학생 — 가짜 모드(GOLDEN_FAKE_LLM=1)에서 페르소나 1종·문제 2개를 끝까지 돌린다.

확인하는 것(지시서 S11 할 일 4):
① golden.turns에 행이 생긴다
② 모든 문제가 graded로 끝난다
③ 학생 LLM 입력(프롬프트)에 닉네임·session_id가 섞이지 않는다
그리고 ③의 검사가 실제로 잡아내는지(섞이면 멈추는지)를 반대 사례로 확인한다.
"""

import asyncio
import uuid

import pytest

from golden import sim_student


def _run(persona: str, n: int, nickname: str) -> sim_student.SimResult:
    """동기 테스트에서 시뮬레이션 1회를 돌린다."""
    return asyncio.run(sim_student.run_simulation(persona, n, nickname=nickname))


def test_fake_persona_two_problems_end_to_end() -> None:
    # 실행마다 새 닉네임(숙련도가 이전 실행과 섞이지 않게) — 형식은 sim-*
    nickname = f"sim-test-{uuid.uuid4().hex[:8]}"
    result = _run("sign-slip", 2, nickname)

    assert result.error is None
    assert result.mode == "fake"
    assert result.student_llm_calls == 0  # 가짜 모드는 학생 LLM을 부르지 않는다

    # ② 두 문제 모두 graded로 끝났다 — 대본대로 오답 1회(튜터 1턴) → 정답
    assert len(result.problems) == 2
    for log in result.problems:
        assert log.correct is True
        assert log.attempts == 2
        assert log.turns_used == 1
        assert len(log.tutor_lines) == 1
    assert result.problems[0].problem_id != result.problems[1].problem_id

    # ① turns 행: 문제마다 tutor_turn 1행 + graded 1행
    rows = asyncio.run(sim_student.fetch_turn_rows(result.session_id))
    assert [r["kind"] for r in rows] == ["tutor_turn", "graded", "tutor_turn", "graded"]
    assert set(rows[0]) == set(sim_student.CSV_COLUMNS)  # CSV 열에 닉네임·session_id 없음

    # ③ 학생 LLM 입력에 닉네임·session_id가 없다(문제당 입력 2회 × 2문제 = 프롬프트 4개)
    assert len(result.prompts) == 4
    for prompt in result.prompts:
        assert nickname not in prompt
        assert result.session_id not in prompt
        assert "sim-" not in prompt


def test_privacy_check_stops_on_leak() -> None:
    # 검사의 변별력: 프롬프트에 닉네임이나 session_id가 들어가면 실제로 멈춰야 한다
    sid = str(uuid.uuid4())
    with pytest.raises(sim_student.SimStudentError):
        sim_student._check_privacy("문제: ... sim-sign-slip ...", "sim-sign-slip", sid)
    with pytest.raises(sim_student.SimStudentError):
        sim_student._check_privacy(f"문제: ... {sid} ...", "sim-sign-slip", sid)
    sim_student._check_privacy("문제: 일차함수", "sim-sign-slip", sid)  # 없으면 통과
