"""S27R(반복 회차 · GOLD-42 · F-02) — 채점 앞말·꼬리 처리 `GOLDEN_T2R_GRADE` 계약.

- 플래그 0(기본): 채점이 이전과 한 입력도 다르지 않다(고정 입력 43행 · 30문항 정답 · 가짜 720 입력).
- 플래그 1: 고정 입력 표의 맞는 입력 11문장이 전부 정답이 되고, 오답 20행 중 정답으로 뒤집히는 것은
  0개다. 지금도 정답인 대조군 11행은 그대로 정답이다.
- 다시 채점은 원래 채점이 **파싱에 실패했을 때만** 한다. 붙여넣기(100자 넘음)는 다시 채점하지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from golden.grade import is_correct
from golden.grade_tail import FLAG_ENV, last_math_fragment, t2r_grade_enabled
from golden.problems import Problem, load_problems
from golden.sim.student import P7_INPUTS

_TABLE = Path(__file__).resolve().parents[2] / "golden" / "data" / "grade_prefix_tail_lf.json"
_ROWS: list[dict[str, Any]] = json.loads(_TABLE.read_text(encoding="utf-8"))["rows"]
_PROBLEMS: dict[str, Problem] = {p["id"]: p for p in load_problems()}
# 플래그 1에서 정답이어야 하는 종류(맞는 입력 + 대조군)
_TRUE_ON = {"correct_with_prefix_tail", "correct_question_form", "correct_now"}


def _grade(row: dict[str, Any]) -> bool:
    return is_correct(_PROBLEMS[row["problem_id"]], row["input"])


@pytest.mark.parametrize("value", [None, "", "0", "true", "TRUE", "yes", " 1"])
def test_flag_is_on_only_for_exact_one(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(FLAG_ENV, raising=False)
    else:
        monkeypatch.setenv(FLAG_ENV, value)
    assert t2r_grade_enabled() is False


def test_flag_one_turns_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FLAG_ENV, "1")
    assert t2r_grade_enabled() is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("f(0)은 8이에요?", "8"),
        ("f(3)=-3-5 같은거야?", "-3-5"),
        ("f(2)는 6*2 - 8이에요?", "6*2-8"),
        ("x=-3을 넣었으니까 f(-3) = -3 + 4 = 1이라고 생각해요.", "1"),
        ("6(2)-8=-4요?", "-4"),  # 대입식이 정답과 같아도 끝값을 본다
        ("6×2 빼기 8 몇이예요?", "8"),  # 한글 연산어는 조각을 끊는다 — 마지막 조각만
        ("6×2−8 이에요?", "6*2-8"),  # 곱셈·빼기 기호를 바꾼다
        ("f(0)은 뭔가요?", "(0)"),
        ("답 모름", None),
        ("", None),
        ("잘 모르겠어요.", None),  # 마침표만 남는 조각은 답이 아니다
    ],
)
def test_last_math_fragment(text: str, expected: str | None) -> None:
    assert last_math_fragment(text) == expected


def test_paste_over_limit_is_not_regraded() -> None:
    """붙여넣기(P7) 속 `x=0`이 LF-06 정답 0과 우연히 맞던 것 — 100자 상한으로 막는다(가짜 720 실측)."""
    paste = max(P7_INPUTS, key=len)
    assert len(paste) > 100
    assert last_math_fragment(paste) is None


@pytest.mark.parametrize("row", _ROWS, ids=[f"{r['problem_id']}:{r['input']}" for r in _ROWS])
def test_flag_off_is_unchanged(monkeypatch: pytest.MonkeyPatch, row: dict[str, Any]) -> None:
    """플래그 0: S26R 특성화와 같은 출력(대조군만 True)."""
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert _grade(row) is (row["kind"] == "correct_now")


@pytest.mark.parametrize("row", _ROWS, ids=[f"{r['problem_id']}:{r['input']}" for r in _ROWS])
def test_flag_on_fixes_prefix_tail_without_flipping_wrong(
    monkeypatch: pytest.MonkeyPatch, row: dict[str, Any]
) -> None:
    """플래그 1: 맞는 입력·대조군은 정답, 오답은 그대로 오답(뒤집힘 0). 모호 1행은 지금 값(오답)을 기록."""
    monkeypatch.setenv(FLAG_ENV, "1")
    assert _grade(row) is (row["kind"] in _TRUE_ON)


def test_flag_on_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """S27R 완료 기준 ②의 숫자 — 맞는 입력 11/11(반복 포함 13/13) · 오답 뒤집힘 0/20."""
    monkeypatch.setenv(FLAG_ENV, "1")
    targets = [
        r for r in _ROWS if r["kind"] in ("correct_with_prefix_tail", "correct_question_form")
    ]
    wrong = [r for r in _ROWS if r["kind"] == "wrong"]
    assert len(targets) == 11 and sum(r["times"] for r in targets) == 13
    assert sum(_grade(r) for r in targets) == 11
    assert len(wrong) == 20 and sum(_grade(r) for r in wrong) == 0


@pytest.mark.parametrize("flag", ["0", "1"])
def test_every_problem_answer_is_still_correct(monkeypatch: pytest.MonkeyPatch, flag: str) -> None:
    """30문항 정답 문자열은 두 플래그 모두 정답 · 숫자 없는 입력은 두 플래그 모두 오답."""
    monkeypatch.setenv(FLAG_ENV, flag)
    assert len(_PROBLEMS) == 30
    for p in _PROBLEMS.values():
        assert is_correct(p, p["answer"]), p["id"]
        assert not is_correct(p, "답 모름"), p["id"]
