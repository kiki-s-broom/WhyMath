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
from golden.problems import Problem, load_problems
from golden.store import TurnRow

from golden import api, tutor

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


# ── 항목 2: 튜터 후반 턴 — 학생 몫을 대신 계산 · 마지막 되묻기가 하위 단계 · 말투 혼용 ─────────
# - S9 14행: 튜터가 학생이 할 0 대입을 대신 써 줬다("x 대신 0을 넣으면 식이 4×0+8이 되는데").
# - S9 16행: 남은 계산을 "0+8은 얼마" 한 칸으로 줄였다.
# - S11 sim_no-setup 20·32행: 같은 형태("남은 0+8을 계산하면" · "3×5+1이 15+1이 된 것이니").
# - S11 3-6 발견 ②: 3번째(마지막) 되묻기가 하위 단계 질문이라 학생의 다음 입력이 그 답인데
#   최종 답으로 채점됐다(sim_no-setup 4·24·28행 → 5·25·29행 등 1차 10건 · 재실행 7건).
#   튜터는 지금 몇 번째 되묻기인지 모른다(사용자 프롬프트에 턴 정보가 없다).
# - 말투: S9 보고 후보 3(튜터 반말 · 판정·앱 문구 존댓말) · S11 sim_sign-slip 11~13행("학생은 …"
#   3인칭) · sim_slope-blind_r2 2~4행(혼자 존댓말). Kiki 결정(2026-11-11): 튜터를 해요체로 맞춘다.
def _turn(n: int, student: str, tutor_text: str) -> TurnRow:
    return TurnRow(turn_no=n, student_text=student, tutor_text=tutor_text, kind="tutor_turn")


def _lf05() -> Problem:
    problem = next(p for p in load_problems() if p["id"] == "LF-05")
    return problem


def test_user_prompt_marks_last_tutor_turn() -> None:
    """S9 16행 재생 — 학생의 3번째 입력(`0이요?`)에 답하는 되묻기는 마지막 차례임을 튜터가 알아야 한다."""
    history = [_turn(1, "12", "…"), _turn(2, "4요?", "…")]
    prompt = tutor.build_user_prompt(_lf05(), history, "0이요?")
    assert "3번 중 3번째" in prompt
    assert "마지막 되묻기" in prompt


def test_user_prompt_first_turn_is_not_marked_last() -> None:
    """S9 14행 재생 — 첫 되묻기에는 '마지막' 표시가 없어야 한다(변별력 대조군)."""
    prompt = tutor.build_user_prompt(_lf05(), [], "12")
    assert "3번 중 1번째" in prompt
    assert "마지막" not in prompt


def test_tutor_max_turns_matches_api_contract() -> None:
    """턴 표시의 분모(3)는 api의 튜터 턴 상한과 같은 값이어야 한다."""
    assert tutor.MAX_TUTOR_TURNS == api.MAX_TUTOR_TURNS == 3


@pytest.mark.parametrize(
    ("rule_text", "log_lines"),
    [
        ("대신", "S9 14·16행 · S11 no-setup 20·32행 — 학생이 할 대입·계산을 튜터가 대신함"),
        ("마지막 되묻기", "S11 발견 ② — 마지막 되묻기가 하위 단계 질문"),
        ("해요체", "S9 후보 3 · S11 r2 2~4행 — 반말·존댓말 혼용(Kiki 결정: 해요체)"),
        ("3인칭", "S11 sign-slip 11~13행 — '학생은 …'"),
    ],
)
def test_tutor_prompt_has_rule_from_logs(rule_text: str, log_lines: str) -> None:
    """튜터 시스템 프롬프트(golden/tutor_prompt.md)에 로그가 가리킨 규칙이 있어야 한다."""
    prompt = tutor.TUTOR_PROMPT_PATH.read_text(encoding="utf-8")
    assert rule_text in prompt, log_lines


# ── 항목 4: 채점기가 중2 말투 꼬리를 붙인 정답을 오답 처리 ─────────────────────────────
# Kiki 결정(2026-11-11): 떼는 꼬리에 `요·이요·?·같아요·같은데요·인가요·맞나요`를 더한다(공유 계약 변경).
# - S11 3-6 발견 ①: 정답 값을 말했는데 거부된 문제 1차 13/30 · 재실행 4/10.
# - S9 8·9·15·16행: 본인 학생도 `12요?`·`-4?`·`4요?`·`0이요?`처럼 꼬리를 붙여 쳤다 — 학생 LLM만의
#   비현실적 입력이 아니다(이 4줄은 값이 틀려 원래도 오답이었고, 고친 뒤에도 오답이어야 한다).
# 앞에 말이 붙은 문장(`음... -3+4요?`·`15+1은 16이요.`)은 그대로 오답이다(보수적 — S11 제안 A).
def _p(pid: str) -> Problem:
    return next(p for p in load_problems() if p["id"] == pid)


@pytest.mark.parametrize(
    ("pid", "text", "log_line"),
    [
        ("LF-05", "8이요", "S11 sim_no-setup 21행"),
        ("LF-02", "1이요?", "S11 sim_slope-blind_r2 8행"),
        ("LF-03", "4요?", "S11 sim_slope-blind_r2 13행"),
        ("LF-08", "16 맞나요?", "S11 sim_slope-blind 24행"),
        ("LF-02", "1 같은데요?", "S11 sim_slope-blind 6행"),
        ("LF-03", "6×2-8이요?", "S11 sim_no-setup 13행(값이 같은 식 — 기존 규칙대로 정답)"),
        ("LF-04", "-3 - 5요?", "S11 sim_no-setup 17행"),
        ("LF-07", "2×2+7이요?", "S11 sim_no-setup 29행"),
        ("LF-01", "-15+3이요?", "S11 sim_slope-blind_r2 5행"),
        ("LF-10", "-10-1이요?", "S11 sim_slope-blind_r2 41행"),
        ("LF-01", "f(5)=-12 같아요", "S11 sim_sign-slip 2행 꼴(= 뒤 + 같아요)"),
        ("LF-04", "-8인가요?", "S11 sim_slope-blind_r2 17행 꼬리"),
    ],
)
def test_answer_with_spoken_tail_is_correct(pid: str, text: str, log_line: str) -> None:
    from golden import grade

    assert grade.is_correct(_p(pid), text), log_line


@pytest.mark.parametrize(
    ("pid", "text", "log_line"),
    [
        ("LF-03", "12요?", "S9 8행(값이 틀림)"),
        ("LF-03", "-4?", "S9 9행(부호가 틀림 — 4와 -4)"),
        ("LF-05", "4요?", "S9 15행(값이 틀림)"),
        ("LF-05", "0이요?", "S9 16행(값이 틀림)"),
        ("LF-02", "음... -3+4요?", "S11 sim_no-setup 9행(앞말이 붙음 — 계속 오답)"),
        ("LF-08", "15+1은 16이요.", "S11 sim_no-setup 33행(문장 속 수 — 계속 오답)"),
        ("LF-01", "더하기요?", "S11 sim_no-setup 4행(수가 아님)"),
        ("LF-05", "요", "꼬리만 있는 입력(빈 답)"),
    ],
)
def test_wrong_or_sentence_answers_stay_wrong(pid: str, text: str, log_line: str) -> None:
    from golden import grade

    assert not grade.is_correct(_p(pid), text), log_line
