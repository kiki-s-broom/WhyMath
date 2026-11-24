"""S28 T2 적용 — 매칭된 오개념 한 줄을 튜터 사용자 프롬프트에 넣고, 오개념 검출률을 잰다(F-05).

무엇을 고정하는가
1. 플래그 0(또는 매칭 없음)이면 튜터 사용자 프롬프트가 S28 이전과 한 글자도 같다(완료 기준 ③).
2. 플래그 1이고 매칭이 있을 때만 지시서 문장 그대로의 한 줄이 학생 입력 바로 뒤에 들어간다.
3. api가 튜터에 넘기는 값: 플래그 1 + 매칭 → 그 오개념 한 줄 설명 · 매칭 없음·플래그 0 → None.
4. 오개념 한 줄 설명에는 숫자가 없고, 어느 문항의 정답도 새지 않는다(설명을 타고 정답이 튜터 문장으로
   넘어가지 않게). 검출 낱말은 행마다 있다.
5. 오개념 검출률(`metrics.misconception_detection`)의 분모·분자·제외 규칙과 집계 도구(`t2_summary`)의
   거부 규칙.

튜터는 GOLDEN_FAKE_LLM=1(conftest)이라 실제 LLM을 부르지 않는다.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from golden.api import app
from golden.eval import misconception_description
from golden.eval.misconception import FLAG_ENV, MISCONCEPTIONS_PATH, answer_table
from golden.eval.rubric import FLAG_ENV as T1_FLAG_ENV
from golden.problems import Problem, load_problems
from golden.sim.t1_summary import SummaryError
from golden.store import TurnRow

from golden import tutor
from golden.sim import metrics, t2_summary

client = TestClient(app)
PROBLEMS = {p["id"]: p for p in load_problems()}

# S28 이전 build_user_prompt(main `ce489827`)가 이 입력에 낸 글 그대로 — 플래그 0 동작 불변의 기준
_HISTORY = [
    TurnRow(1, "6/(-9)", "어느 쪽이 먼저일까?", "tutor_turn"),
    TurnRow(2, "모르겠어요", "다시 볼까?", "tutor_turn"),
]
_BEFORE_S28 = (
    "문제: 일차함수의 그래프가 두 점 $(-2, 5)$, $(4, -4)$를 지날 때, 이 그래프의 기울기를 구하시오.\n"
    "참고 힌트(정답 아님, 그대로 읽지 말 것): y의 값의 증가량을 x의 값의 증가량으로 나누면 돼. "
    "증가량이 음수일 수도 있다는 점에 주의해 볼래?\n"
    "학생: 6/(-9)\n튜터: 어느 쪽이 먼저일까?\n학생: 모르겠어요\n튜터: 다시 볼까?\n학생: 6/(-9)요\n"
    "되묻기 차례: 3번 중 3번째 — 마지막 되묻기다. 학생의 다음 입력이 바로 채점된다.\n"
    "위 학생 말에 대한 튜터의 다음 한 마디를 써라."
)

# 지시서 S28 할 일 1의 문장(설명 자리만 채운다)
_HINT = "학생의 답은 '{d}' 유형의 실수일 수 있다. 정답은 말하지 말고 그 지점을 짚어 묻는다."


# ── 1·2. 프롬프트 ───────────────────────────────────────────────────────────────


def test_prompt_without_misconception_is_unchanged_from_before_s28() -> None:
    """설명이 없으면(플래그 0·매칭 없음) S28 이전 글과 한 글자도 같다."""
    lf14 = PROBLEMS["LF-14"]
    assert tutor.build_user_prompt(lf14, _HISTORY, "6/(-9)요") == _BEFORE_S28
    assert tutor.build_user_prompt(lf14, _HISTORY, "6/(-9)요", None) == _BEFORE_S28


def test_prompt_with_misconception_adds_exactly_one_line_after_student() -> None:
    """설명이 있으면 지시서 문장 한 줄이 마지막 학생 입력 바로 뒤에 들어가고, 나머지는 그대로다."""
    lf14 = PROBLEMS["LF-14"]
    description = misconception_description("M0568")
    got = tutor.build_user_prompt(lf14, _HISTORY, "6/(-9)요", description).split("\n")
    before = _BEFORE_S28.split("\n")
    student_at = before.index("학생: 6/(-9)요")
    assert got[: student_at + 1] == before[: student_at + 1]
    assert got[student_at + 1] == _HINT.format(d=description)
    assert got[student_at + 2 :] == before[student_at + 1 :]
    assert tutor.T2_HINT_TEMPLATE.format(description="X") == _HINT.format(d="X")


# ── 3. api → 튜터 ──────────────────────────────────────────────────────────────


def _capture_ask(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """tutor.ask를 가로채 넘어온 misconception 값을 모은다(응답은 가짜 문장 그대로)."""
    seen: list[str | None] = []
    real = tutor.ask

    async def fake_ask(
        problem: Problem,
        history: list[TurnRow],
        student_text: str,
        misconception: str | None = None,
    ) -> tutor.TutorReply:
        seen.append(misconception)
        return await real(problem, history, student_text, misconception)

    monkeypatch.setattr(tutor, "ask", fake_ask)
    return seen


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("1", [misconception_description("M0037"), None, misconception_description("M0037")]),
        ("0", [None, None, None]),
    ],
    ids=["flag-on", "flag-off"],
)
def test_api_passes_description_only_when_flag_on_and_matched(
    monkeypatch: pytest.MonkeyPatch, flag: str, expected: list[str | None]
) -> None:
    """LF-01(정답 −12) 되묻기 3턴: `0`(M0037)·`999999`(매칭 없음)·`0이요?`(M0037)."""
    monkeypatch.setenv(FLAG_ENV, flag)
    monkeypatch.delenv(T1_FLAG_ENV, raising=False)
    seen = _capture_ask(monkeypatch)
    r = client.post("/golden/session", json={"nickname": f"t2a-{flag}-{uuid.uuid4().hex[:6]}"})
    session_id = r.json()["session_id"]
    for text in ("0", "999999", "0이요?"):
        r = client.post(
            "/golden/answer", json={"session_id": session_id, "problem_id": "LF-01", "text": text}
        )
        assert r.status_code == 200 and r.json()["kind"] == "tutor_turn"
    assert seen == expected


# ── 4. 설명·낱말 데이터 ──────────────────────────────────────────────────────────


def _rows() -> list[dict[str, Any]]:
    raw = json.loads(MISCONCEPTIONS_PATH.read_text(encoding="utf-8"))
    rows = raw["misconceptions"]
    assert isinstance(rows, list)
    return rows


def test_every_misconception_has_digit_free_description_and_keywords() -> None:
    """11행 모두: 설명은 숫자 없는 한 줄 · 검출 낱말 1개 이상 · 매칭표의 ID는 전부 설명이 있다."""
    rows = _rows()
    assert len(rows) == 11
    for row in rows:
        description = row["prompt_description"]
        assert description.strip() and "\n" not in description, row["mis_id"]
        assert not any(ch.isdigit() for ch in description), row["mis_id"]
        assert row["keywords"] and all(str(k).strip() for k in row["keywords"]), row["mis_id"]
    matched_ids = {mis_id for pairs in answer_table().values() for mis_id, _ in pairs}
    assert all(misconception_description(mis_id) for mis_id in matched_ids)
    assert t2_summary.keyword_table().keys() == {str(r["mis_id"]) for r in rows}


def test_hint_line_never_leaks_the_problem_answer() -> None:
    """매칭표 70행 전부: 튜터에 넣는 한 줄이 그 문항 정답을 유출로 판정받지 않는다."""
    checked = 0
    for problem_id, pairs in answer_table().items():
        answer = PROBLEMS[problem_id]["answer"]
        for mis_id, _ in pairs:
            line = tutor.T2_HINT_TEMPLATE.format(description=misconception_description(mis_id))
            assert metrics.detect_answer_leakage(line, answer) != metrics.LeakageVerdict.leaked
            checked += 1
    assert checked == 70


# ── 5. 오개념 검출률 ─────────────────────────────────────────────────────────────

_BUNDLES = {("LF-01", "0"): ("M0037",), ("LF-14", "-3/2x"): ("M0034", "M0568")}
_KEYWORDS = {"M0037": ("대입",), "M0034": ("y절편",), "M0568": ("분자", "y의 변화량")}


def _session(persona: str, problem_id: str, forced: str | None, *tutors: str) -> dict[str, Any]:
    turns = [
        {"n": i + 1, "student": "s", "tutor": t, "kind": "tutor_turn", "correct": False}
        for i, t in enumerate(tutors)
    ]
    turns.append(
        {"n": len(turns) + 1, "student": "s", "tutor": "f", "kind": "graded", "correct": False}
    )
    return {"persona": persona, "problem_id": problem_id, "forced_answer": forced, "turns": turns}


def test_detection_counts_only_p3_sessions_with_an_injected_misconception() -> None:
    """분모 = P3 · 오개념 묶음 주입 · 되묻기 1번 이상. 묶음 안 어느 오개념의 낱말이든 검출로 센다."""
    sessions = [
        _session("P3", "LF-01", "0", "x에 5를 대입해 볼래?"),  # 검출
        _session("P3", "LF-01", "0", "다시 볼까?", "어디가 막혀?"),  # 미검출
        _session(
            "P3", "LF-14", "-3/2x", "y 의 변화량은 얼마야?"
        ),  # 공백이 달라도 검출(묶음 둘째 ID)
        _session("P3", "LF-14", "7", "대입해 봐"),  # OP 코드만 주입 → 제외
        _session("P3", "LF-01", "0"),  # 되묻기 없음 → 제외
        _session("P2", "LF-01", "0", "대입해 봐"),  # P3 아님 → 무시
    ]
    got = metrics.misconception_detection(sessions, _BUNDLES, _KEYWORDS)
    assert (got["detected_sessions"], got["eligible_sessions"]) == (2, 3)
    assert got["value"] == round(2 / 3, 4) and got["pass"] is True
    assert (got["excluded_op_only"], got["excluded_no_tutor_turn"]) == (1, 1)
    assert got["by_bundle"] == {
        "M0034·M0568": {"eligible": 1, "detected": 1},
        "M0037": {"eligible": 2, "detected": 1},
    }


def test_detection_without_eligible_sessions_is_unknown_not_pass() -> None:
    """분모가 0이면 값은 None이고 통과가 아니다 · 빈 낱말은 검출이 아니다."""
    got = metrics.misconception_detection([_session("P1", "LF-01", None, "대입")], _BUNDLES, {})
    assert got["value"] is None and got["pass"] is False
    assert metrics.mentions_misconception("아무 말", ("", "  ")) is False


def test_injection_bundles_cover_the_70_injector_answers() -> None:
    """묶음 키 49개 · 묶음에 든 ID 70개(S27 매칭표와 같은 조합) · 둘 이상인 묶음은 S27의 세 쌍뿐."""
    bundles = t2_summary.injection_bundles()
    assert sum(len(ids) for ids in bundles.values()) == 70
    assert len(bundles) == 49
    assert {ids for ids in bundles.values() if len(ids) > 1} == {
        ("M0035", "M0569"),
        ("M0034", "M0568"),
        ("M0002", "M0548"),
    }


def test_keyword_table_refuses_an_empty_keyword_row(tmp_path: Path) -> None:
    """낱말이 빈 행이 있으면 집계를 거부한다(빈 낱말은 늘 미검출로 숨는다)."""
    raw = json.loads(MISCONCEPTIONS_PATH.read_text(encoding="utf-8"))
    raw["misconceptions"][0]["keywords"] = ["  "]
    path = tmp_path / "m.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SummaryError, match="keywords"):
        t2_summary.keyword_table(path)


def _summary(flag: str, m1: float | None, detection: float | None) -> dict[str, Any]:
    metric = {
        "M1": {"value": m1},
        "M2": {"value": 2.0},
        "M3": {"value": 0.0},
        "M4": {"value": 0},
        "M5": {"value": 0},
    }
    return {
        "run_dir": f"f{flag}",
        "t2_flag": flag,
        "mode": "live",
        "planned_sessions": 720,
        "skipped_sessions": 0,
        "sessions": 720,
        "personas": ["P3"],
        "metrics": metric,
        "degraded_tutor_turns": 0,
        "detection": {
            "value": detection,
            "detected_sessions": 0,
            "eligible_sessions": 0,
            "excluded_op_only": 0,
            "excluded_no_tutor_turn": 0,
            "by_bundle": {},
        },
    }


def test_compare_refuses_wrong_flag_order_and_unknown_numbers_fail() -> None:
    """전후 플래그가 0→1이 아니면 거부 · 숫자가 없으면 그 기준은 실패(모름 ≠ 통과)."""
    with pytest.raises(SummaryError, match="0→1"):
        t2_summary.compare(_summary("1", 0.0, 0.5), _summary("0", 0.0, 0.5))
    ok = t2_summary.compare(_summary("0", 0.01, 0.4), _summary("1", 0.0, 0.7))
    assert ok["criterion_one_met"] and ok["criterion_two_met"]
    assert ok["checks"]["detection_at_least_60pct"] is True
    unknown = t2_summary.compare(_summary("0", 0.0, 0.4), _summary("1", None, None))
    assert unknown["criterion_one_met"] is False and unknown["criterion_two_met"] is False
    assert "| 오개념 검출률(P3) | 0.4 | — |" in t2_summary.render_markdown(unknown)
