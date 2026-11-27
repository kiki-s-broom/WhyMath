"""S26R(반복 회차 · GOLD-42 · F-02) 특성화 — 채점 앞말·꼬리 입력에서 지금 채점기가 무엇을 내는가.

옛 자산이 없다(HARVEST.md 「반복 슬롯 T2R 경계 (S26R)」) — 그래서 지시서대로 **지금의**
`golden.grade.is_correct` 출력을 고정 입력 표 전부에 대해 고정한다. 동작이 맞는지는 묻지 않고,
바뀌지 않는지만 본다. S27R이 플래그 뒤에 새 처리를 붙이면, 플래그 0일 때 이 테스트가 그대로 초록이어야 한다.

고정 입력 표: `golden/data/grade_prefix_tail_lf.json`(1단계 S24·S29·S33 보고에서 옮긴 시뮬레이터 발화).
옛 후보 `whymath_backend.l3.verify_final_answer.verify_final_answer`를 버린 근거도 같은 표로 고정한다
(테스트는 옛 모듈을 옛 자리에서 부를 수 있다 — 골든 코드는 import하지 않는다).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from golden.grade import is_correct
from golden.problems import Problem, load_problems

_TABLE = Path(__file__).resolve().parents[3] / "golden" / "data" / "grade_prefix_tail_lf.json"
_ROWS: list[dict[str, Any]] = json.loads(_TABLE.read_text(encoding="utf-8"))["rows"]
_PROBLEMS: dict[str, Problem] = {p["id"]: p for p in load_problems()}

# 지금 채점기가 정답으로 받는 것은 "지금도 정답(대조군)" 종류뿐이다
_ACCEPTED_NOW = {"correct_now"}


def test_table_shape() -> None:
    """표가 지시서 S26R 완료 기준 ①을 채운다(공허한 통과 금지)."""
    kinds = [r["kind"] for r in _ROWS]
    correct_inputs = [
        r for r in _ROWS if r["kind"].startswith("correct_") and r["kind"] != "correct_now"
    ]
    assert sum(r["times"] for r in correct_inputs) >= 13  # 맞는 식·값이 든 오답 입력(반복 포함)
    assert len(correct_inputs) >= 11  # 서로 다른 문장
    assert kinds.count("wrong") >= 20
    assert all(r["source"] for r in _ROWS)
    assert all(r["problem_id"] in _PROBLEMS for r in _ROWS)


@pytest.mark.parametrize("row", _ROWS, ids=[f"{r['problem_id']}:{r['input']}" for r in _ROWS])
def test_current_grader_output_is_frozen(row: dict[str, Any]) -> None:
    """지금 채점기의 출력 — 대조군만 True, 나머지(맞는 식이 든 입력 포함)는 전부 False."""
    got = is_correct(_PROBLEMS[row["problem_id"]], row["input"])
    assert got is (row["kind"] in _ACCEPTED_NOW)


def test_rejected_legacy_candidate_accepts_none_of_the_correct_inputs() -> None:
    """옛 후보 `verify_final_answer`를 버린 근거 — 맞는 입력 11문장을 하나도 correct로 받지 않는다.

    대조군 11개 중에서도 correct는 1개뿐이고 2개는 incorrect다(골든 채점기보다 거짓 오답이 많다).
    """
    from whymath_backend.l3.verify_final_answer import verify_final_answer

    def state(row: dict[str, Any]) -> str:
        p = _PROBLEMS[row["problem_id"]]
        view = SimpleNamespace(
            answer=p["answer"],
            choices=None,
            question_format=None,
            answer_format=None,
            multiple_answers=None,
        )
        return str(verify_final_answer(row["input"], view).state.value)

    targets = [
        r for r in _ROWS if r["kind"] in ("correct_with_prefix_tail", "correct_question_form")
    ]
    controls = [r for r in _ROWS if r["kind"] == "correct_now"]
    assert [state(r) for r in targets].count("correct") == 0
    control_states = [state(r) for r in controls]
    assert control_states.count("correct") == 1
    assert control_states.count("incorrect") == 2


@pytest.mark.parametrize("row", _ROWS, ids=[f"{r['problem_id']}:{r['input']}" for r in _ROWS])
def test_t2r_flag_has_no_effect_after_s30r_revert(
    row: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """S30R 판정 '효과 없음'으로 T2R 연결을 되돌렸다 — 플래그를 1로 켜도 출력이 꺼진 것과 같다.

    (S30R 보고 · 1회차 S30 선례 — 고정 입력 표와 이 특성화 테스트만 남긴다)
    """
    monkeypatch.setenv("GOLDEN_T2R_GRADE", "1")
    got = is_correct(_PROBLEMS[row["problem_id"]], row["input"])
    assert got is (row["kind"] in _ACCEPTED_NOW)
