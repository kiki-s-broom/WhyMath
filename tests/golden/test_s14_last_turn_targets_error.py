"""S14 — FINDINGS 1위(GP-4) 재현: 마지막 되묻기가 학생 답의 틀린 곳을 짚지 않는다(루브릭 C5).

근거 로그(golden/FINDINGS.md 「1위 끊김 지점」):
- [본인 · S10 전] S9 9행 LF-03: 학생 `-4?`(12−8을 −4로) → 튜터가 부호·뺄셈 방향을 짚지 않고
  "8을 빼면 얼마"만 되풀이했다. S10 재생(프롬프트 수정 뒤)에서도 3턴이 "끝까지 계산"만 물었다.
- [본인 역할 규칙 없음 · S10 후] S12 LF-14: 학생 `6/(-9)`(분자·분모 뒤바꿈) → 마지막 턴이 뒤바뀐 곳을
  이름 붙이지 않고 "기울기의 최종 값을 직접 말해 볼래요?"만 물었다.
- [AI · S10 후] S12 sign-slip 재실행 4·8·27행(LF-01·02·10): 부호를 틀린 답에 마지막 턴이
  "값을 직접 구해 말해 볼래요?"만 물었다.

S10 규칙 6(마지막 되묻기는 최종 값을 묻는다)은 유지한다. 고칠 것은 규칙 6에 한 문장 —
"직전 답에 틀린 곳이 보이면 마지막 되묻기에서도 그 곳 하나를 짚은 뒤 답을 묻는다"이다.
테스트는 실제 LLM을 부르지 않는다(공통 규칙 8). LLM의 실제 반응은 보고서의 재생 표로 잰다.
"""

from __future__ import annotations

import pytest
from golden.problems import Problem, load_problems
from golden.store import TurnRow

from golden import tutor


def _rule6() -> str:
    """튜터 시스템 프롬프트에서 규칙 6 한 줄만 꺼낸다(다른 규칙에 같은 낱말이 있어도 속지 않게)."""
    lines = tutor.TUTOR_PROMPT_PATH.read_text(encoding="utf-8").splitlines()
    found = [line for line in lines if line.startswith("6.")]
    assert len(found) == 1, "규칙 6 줄이 정확히 1개여야 한다"
    return found[0]


def _problem(pid: str) -> Problem:
    return next(p for p in load_problems() if p["id"] == pid)


def _turn(n: int, student: str) -> TurnRow:
    return TurnRow(turn_no=n, student_text=student, tutor_text="…", kind="tutor_turn")


# ── 재현(수정 전 빨강): 규칙 6이 마지막 차례에 틀린 곳을 짚으라고 말하지 않는다 ─────────────────
def test_rule6_tells_last_turn_to_point_at_wrong_spot() -> None:
    """S9 9행 · S12 LF-14 · sign-slip 4·8·27행 — 마지막 되묻기에서도 틀린 곳 하나를 짚어야 한다."""
    rule = _rule6()
    assert "마지막 되묻기에서도" in rule, "마지막 차례에도 적용됨을 규칙 6이 직접 말해야 한다"
    assert "틀린 곳" in rule, "규칙 6이 학생 답의 틀린 곳을 짚으라고 말해야 한다"
    assert "쓰인 말·값 그대로" in rule, "짚는 대상은 학생이 실제로 쓴 말·값이어야 한다"
    assert (
        "질문 하나로" in rule
    ), "짚기와 답 묻기를 질문 하나로 묶어야 한다(규칙 2 — 1차 문장 재생에서 2질문)"


def test_rule6_new_sentence_does_not_say_student() -> None:
    """1차 문장('학생이 쓴 말·값')으로 재생하자 '학생이 직접 써 볼래요?' 3인칭이 0→6턴 생겼다(규칙 7).

    새로 더한 문장에는 '학생'이라는 낱말을 넣지 않는다.
    """
    rule = _rule6()
    added = rule.split("바로 채점된다.", 1)[1]
    assert "틀린 곳" in added
    assert "학생" not in added


# ── 대조군(수정 전에도 초록): 바꾸지 않는 것 ─────────────────────────────────────────────
def test_rule6_still_asks_for_final_answer() -> None:
    """S10이 고친 것(마지막 되묻기 = 최종 값 묻기)은 그대로여야 한다 — S11 발견 ②의 재발 방지."""
    rule = _rule6()
    assert "하위 단계 하나를 묻지 않는다" in rule
    assert "답을 직접 구해 말하도록" in rule


def test_rule1_no_answer_is_kept() -> None:
    """규칙 1(정답·최종 수치를 말하지 않는다)은 그대로다."""
    prompt = tutor.TUTOR_PROMPT_PATH.read_text(encoding="utf-8")
    assert "정답이나 최종 수치를 절대 말하지 않는다" in prompt


# ── 재현(수정 전 빨강): 틀린 곳을 짚을 때도 고친 값을 말하지 않는다는 문장이 규칙 6에 있어야 한다 ─────
def test_rule6_pointing_never_reveals_corrected_value() -> None:
    """짚기 규칙이 '고친 값 알려 주기'로 미끄러지지 않게 같은 줄에 금지를 둔다(규칙 1 대신 계산 방지)."""
    assert "고친 값이나 정답은 말하지 않는다" in _rule6()


@pytest.mark.parametrize(
    ("pid", "earlier", "last", "log_line"),
    [
        ("LF-03", ["20", "12요?"], "-4?", "S9 9행(본인 · S10 전)"),
        ("LF-14", ["-(2/3)", "(4-(-2))/(-4-5)"], "6/(-9)", "S12 LF-14(본인 역할 규칙 없음)"),
        ("LF-01", ["f(5)=18이에요.", "f(5)=-3×5+3=18이에요."], "15이에요.", "sign-slip 재실행 4행"),
    ],
)
def test_last_turn_prompt_carries_the_wrong_answer(
    pid: str, earlier: list[str], last: str, log_line: str
) -> None:
    """마지막 차례의 사용자 프롬프트에 학생이 방금 쓴 틀린 답이 그대로 들어간다(짚을 재료가 모델에 간다)."""
    history = [_turn(i + 1, text) for i, text in enumerate(earlier)]
    prompt = tutor.build_user_prompt(_problem(pid), history, last)
    assert f"학생: {last}" in prompt, log_line
    assert "마지막 되묻기" in prompt, log_line
