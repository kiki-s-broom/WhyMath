"""S27 T2 연결 — 매칭 `golden.eval.misconception`과 플래그 `GOLDEN_T2_MISCONCEPTION`(다섯 걸음 ③④ · 인용 F-05).

무엇을 고정하는가
1. 매칭용 표 파일(`golden/data/misconception_answers_lf.json`)이 지금 주입기가 만드는 표와 글자까지 같다.
2. 주입기 표(S17 `injection_table.csv`)의 오개념 조합 전수 70개 검증 — 원래 ID 49 · 답이 같은 다른 ID 21
   · 실패 0(S27 보고 「검증 1」). 숫자가 바뀌면 보고도 다시 써야 하므로 여기서 고정한다.
   완료 기준 ①은 Kiki 결정 ⓐ(2026-11-24)로 "오개념 묶음 안의 ID" 성공 70/70이다.
3. 실제 오답(저장소에 인용된 사람 출처 17개)의 매칭 결과 — 5/17(S27 보고 「검증 2」).
4. 플래그 꺼짐·켜짐 두 상태 모두 골든 패스가 초록이고 응답이 같다. 켜짐이면 오답 턴마다(되묻기 3턴 +
   마지막 오답 판정) eval_log에 `t2_misconception_id`가 남고, 꺼짐이면 남지 않는다.
5. T1과 T2를 함께 켜면 같은 턴의 eval_log 한 행에 두 기록이 합쳐진다(PK 충돌 없음).
6. 기록이 DB·연결 오류로 실패해도 응답은 그대로고 경고 로그에 예외 타입명이 남는다.

튜터는 GOLDEN_FAKE_LLM=1(conftest)이라 실제 LLM을 부르지 않는다.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from golden.api import app
from golden.eval import T2_MATCHER_VERSION, match_misconception, misconception_enabled
from golden.eval.misconception import ANSWERS_PATH, FLAG_ENV, answer_table
from golden.eval.rubric import FLAG_ENV as T1_FLAG_ENV
from golden.problems import Problem, load_problems
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from golden import api, grade, store
from golden.sim import errors

client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parents[2]
PROBLEMS = {p["id"]: p for p in load_problems()}
INJECTION_CSV = REPO_ROOT / "golden" / "reports_phase1" / "S17" / "injection_table.csv"


# ── 1. 표 파일 ──────────────────────────────────────────────────────────────────


def test_flag_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """플래그 기본값은 끔 — `1`일 때만 켜진다."""
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert misconception_enabled() is False
    for value in ("0", "", "true", " 1"):
        monkeypatch.setenv(FLAG_ENV, value)
        assert misconception_enabled() is False, value
    monkeypatch.setenv(FLAG_ENV, "1")
    assert misconception_enabled() is True


def test_answer_file_matches_injector_now() -> None:
    """커밋된 매칭용 표가 지금 주입기로 다시 만든 글과 같다(주입기·오개념 표가 바뀌면 여기서 걸린다)."""
    expected = errors.misconception_answers_document(load_problems())
    assert ANSWERS_PATH.read_text(encoding="utf-8") == expected


def test_answer_table_has_70_rows_over_11_ids() -> None:
    """70행 · 오개념 ID 9종(M0409·M0567은 맞는 문항이 없다)."""
    table = answer_table()
    pairs = [pair for rows in table.values() for pair in rows]
    assert len(pairs) == 70
    assert {mis_id for mis_id, _ in pairs} == set(errors.ALL_MISCONCEPTIONS) - {"M0409", "M0567"}


# ── 2. 주입기 표 전수 검증 ───────────────────────────────────────────────────────


def _injector_rows() -> list[dict[str, str]]:
    """S17 주입 표에서 오개념 ID가 있고 틀린 답이 만들어진 행(70)."""
    with INJECTION_CSV.open(encoding="utf-8", newline="") as handle:
        return [r for r in csv.DictReader(handle) if r["오개념ID"] and r["틀린답"]]


def _same_answer_ids(rows: list[dict[str, str]], row: dict[str, str]) -> set[str]:
    """같은 문항에서 이 행의 틀린 답과 같은 답(채점 규칙 기준)을 내는 오개념 ID 묶음."""
    problem = PROBLEMS[row["문항"]]
    return {
        other["오개념ID"]
        for other in rows
        if other["문항"] == row["문항"]
        and grade.is_correct({**problem, "answer": other["틀린답"]}, row["틀린답"])
    }


def test_injector_answers_return_original_or_indistinguishable_id() -> None:
    """70개 전수: 원래 ID 49 · 같은 답의 다른 ID 21 · 실패 0. OP별 내역도 고정한다."""
    rows = _injector_rows()
    assert len(rows) == 70
    outcome: Counter[str] = Counter()
    by_op: dict[str, Counter[str]] = {}
    for row in rows:
        got = match_misconception(PROBLEMS[row["문항"]], row["틀린답"])
        if got == row["오개념ID"]:
            kind = "original"
        elif got in _same_answer_ids(rows, row):
            kind = "indistinguishable"
        else:
            kind = "fail"
        outcome[kind] += 1
        by_op.setdefault(row["OP"], Counter())[kind] += 1
    assert outcome == Counter(original=49, indistinguishable=21)
    assert {op: dict(c) for op, c in by_op.items()} == {
        "OP_01": {"original": 6, "indistinguishable": 1},
        "OP_02": {"original": 11},
        "OP_03": {"original": 5},
        "OP_04": {"original": 11, "indistinguishable": 8},
        "OP_07": {"original": 4},
        "OP_08": {"original": 12, "indistinguishable": 12},
    }


def test_criterion_1_bundle_success_is_70_of_70() -> None:
    """완료 기준 ①(Kiki 결정 ⓐ · 2026-11-24): 성공 = "그 답을 만들 수 있는 오개념 묶음 안의 ID".

    모집단 70개 전수가 성공해야 한다(70/70). 겹치는 쌍은 답만으로 가를 수 없으므로 묶음 안이면 성공이다.
    이 숫자는 같은 주입기로 만든 표를 되돌려 보는 왕복 일관성 검사다 — 실제 성능은 사람 출처 5/17이 말한다.
    """
    rows = _injector_rows()
    assert len(rows) == 70
    # 행마다: 매칭 결과가 그 행 틀린 답의 오개념 묶음 안에 있는가(None이면 실패)
    successes = sum(
        1
        for row in rows
        if match_misconception(PROBLEMS[row["문항"]], row["틀린답"]) in _same_answer_ids(rows, row)
    )
    assert successes == 70


def test_indistinguishable_pairs_are_the_three_known_pairs() -> None:
    """답만으로 가를 수 없는 쌍은 셋뿐이다 — M0035·M0569 · M0034·M0568 · M0002·M0548."""
    rows = _injector_rows()
    pairs = {
        tuple(sorted(_same_answer_ids(rows, row)))
        for row in rows
        if len(_same_answer_ids(rows, row)) > 1
    }
    assert pairs == {("M0035", "M0569"), ("M0034", "M0568"), ("M0002", "M0548")}


def test_match_respects_grading_shapes_and_returns_none_otherwise() -> None:
    """채점기가 받는 모양(말꼬리·풀이식)은 같은 답으로 · 질문·엉뚱한 값·정답은 None."""
    lf01 = PROBLEMS["LF-01"]  # f(5), 정답 -12 · M0037(대입 오류)의 틀린 답 0
    assert match_misconception(lf01, "0") == "M0037"
    assert match_misconception(lf01, "0이요?") == "M0037"
    assert match_misconception(lf01, "f(5)=0") == "M0037"
    assert match_misconception(lf01, "x가 뭐예요?") is None
    assert match_misconception(lf01, "999999") is None
    assert match_misconception(lf01, "-12") is None
    assert match_misconception({**lf01, "id": "LF-99"}, "0") is None  # 표에 없는 문항


# ── 3. 실제 오답(사람 출처 · 저장소에 인용된 것) ─────────────────────────────────────

# (출처, 문항, 입력, 매칭 결과) — S9 보고 표 · S12 adult-1 기록 · FINDINGS 근거 로그 2번에서 옮김
_HUMAN_WRONG: list[tuple[str, str, str, str | None]] = [
    ("본인 S9", "LF-02", "7", None),
    ("본인 S9", "LF-03", "20", None),
    ("본인 S9", "LF-03", "12요?", None),
    ("본인 S9", "LF-03", "-4?", "M0037"),
    ("본인 S9", "LF-03", "-4", "M0037"),
    ("본인 S9", "LF-05", "12", None),
    ("본인 S9", "LF-05", "4요?", None),
    ("본인 S9", "LF-05", "0이요?", "M0037"),
    ("본인 S9", "LF-05", "0", "M0037"),
    ("본인 역할 규칙 없음", "LF-14", "6/(-9)", "M0568"),
    ("본인 역할 규칙 없음", "LF-14", "-0.67", None),
    ("성인 adult-1", "LF-10", "9", None),
    ("성인 adult-1", "LF-12", "6", None),
    ("성인 adult-1", "LF-19", "3", None),
    ("성인 adult-1", "LF-19", "6", None),
    ("성인 adult-1", "LF-21", "y=2x+4", None),
    ("성인 adult-1", "LF-24", "y=-2x-2", None),
]


def test_human_source_wrong_answers_match_5_of_17() -> None:
    """사람 출처 값·식 오답 17개 중 5개가 매칭된다(낮아도 고치지 않는다 — 숫자만 · 지시서 할 일 4)."""
    got = [
        (src, pid, text, match_misconception(PROBLEMS[pid], text))
        for src, pid, text, _ in _HUMAN_WRONG
    ]
    assert got == _HUMAN_WRONG
    assert sum(1 for *_, mis_id in got if mis_id) == 5


# ── 4·5. 플래그 0/1 골든 패스 · T1과 합쳐짐 ─────────────────────────────────────────


async def _eval_by_turn(session_id: str) -> list[tuple[str, dict[str, Any] | None]]:
    """세션의 턴(기록 순서)마다 (kind, eval_log JSON 또는 None)."""
    await store.ensure_schema()
    async with store._engine().connect() as conn:
        rows = (
            await conn.execute(
                select(store.turns.c.kind, store.eval_log.c.verdict_json)
                .select_from(
                    store.turns.outerjoin(
                        store.eval_log, store.eval_log.c.turn_id == store.turns.c.id
                    )
                )
                .where(store.turns.c.session_id == uuid.UUID(session_id))
                .order_by(store.turns.c.id)
            )
        ).all()
    return [(str(r.kind), r.verdict_json) for r in rows]


# LF-01에서 오답 4번(되묻기 3턴 + 마지막 오답 판정): 매칭되는 답과 안 되는 답을 섞는다
_WRONG_INPUTS = ("0", "999999", "0이요?", "모르겠어요")
_EXPECTED_IDS = ["M0037", None, "M0037", None]


def _run_lf01_four_wrong(nickname: str) -> tuple[str, list[dict[str, Any]]]:
    """세션 하나에서 LF-01에 오답 4번 — 응답 본문들을 돌려준다."""
    r = client.post("/golden/session", json={"nickname": nickname})
    assert r.status_code == 200
    session_id = r.json()["session_id"]
    bodies = []
    for text in _WRONG_INPUTS:
        r = client.post(
            "/golden/answer",
            json={"session_id": session_id, "problem_id": "LF-01", "text": text},
        )
        assert r.status_code == 200
        bodies.append(r.json())
    assert [b["kind"] for b in bodies] == ["tutor_turn"] * 3 + ["graded"]
    assert bodies[-1]["correct"] is False
    return session_id, bodies


@pytest.mark.parametrize("flag", ["0", "1"], ids=["flag-off", "flag-on"])
def test_golden_path_green_and_t2_log_only_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """두 상태 모두 초록. 켜짐이면 오답 턴 4개 모두에 매칭 결과(None 포함)가 남고, 꺼짐이면 없다."""
    monkeypatch.setenv(FLAG_ENV, flag)
    monkeypatch.delenv(T1_FLAG_ENV, raising=False)
    session_id, _ = _run_lf01_four_wrong(f"t2-{flag}-{uuid.uuid4().hex[:6]}")
    logged = asyncio.run(_eval_by_turn(session_id))
    assert [kind for kind, _ in logged] == ["tutor_turn"] * 3 + ["graded"]
    if flag == "1":
        assert [v and v.get("t2_misconception_id") for _, v in logged] == _EXPECTED_IDS
        assert all(v is not None and v["t2_matcher"] == T2_MATCHER_VERSION for _, v in logged)
        assert all(
            set(v or {}) == {"t2_matcher", "t2_misconception_id", "t2_prompt_hint"}
            for _, v in logged
        )
        # S28은 매칭된 되묻기 턴에 한 줄을 넣었다(True) — S30 되돌림 뒤에는 어느 턴에도 넣지 않는다
        assert [v and v["t2_prompt_hint"] for _, v in logged] == [False] * 4
    else:
        assert [v for _, v in logged] == [None] * 4


def test_response_identical_with_t2_flag_off_and_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """가짜 LLM에서는 플래그 0과 1의 응답이 한 글자도 다르지 않다.

    S30이 튜터 프롬프트 한 줄(S28)을 되돌려, 켜짐이어도 튜터는 같은 프롬프트를 받는다 —
    튜터에 오개념이 가지 않음은 `test_t2_apply.py`가 보고, 여기서는 응답 모양이 같은지 본다.
    """
    monkeypatch.delenv(T1_FLAG_ENV, raising=False)
    results = {}
    for value in ("0", "1"):
        monkeypatch.setenv(FLAG_ENV, value)
        _, bodies = _run_lf01_four_wrong(f"t2-same-{value}-{uuid.uuid4().hex[:6]}")
        results[value] = bodies
    assert results["0"] == results["1"]
    assert set(results["1"][0]) == {"kind", "message", "turn"}  # 매칭 칸이 새어 나가지 않는다


def test_t1_and_t2_merge_into_one_eval_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """T1·T2를 함께 켜면 되묻기 턴의 한 행에 두 기록이 함께 있다. 판정 턴은 T2만(T1은 되묻기 전용)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setenv(T1_FLAG_ENV, "1")
    session_id, _ = _run_lf01_four_wrong(f"t2-both-{uuid.uuid4().hex[:6]}")
    logged = asyncio.run(_eval_by_turn(session_id))
    for kind, verdict in logged:
        assert verdict is not None
        assert "t2_misconception_id" in verdict
        assert ("evaluator" in verdict) is (kind == "tutor_turn")
    assert [v and v["t2_misconception_id"] for _, v in logged] == _EXPECTED_IDS


# ── 6. 기록 실패 ─────────────────────────────────────────────────────────────────


async def _record_raises_db(turn_id: int, verdict: dict[str, object]) -> None:
    raise OperationalError("INSERT", {}, Exception("주입한 실패"))


async def _record_raises_os(turn_id: int, verdict: dict[str, object]) -> None:
    raise ConnectionRefusedError("주입한 연결 실패")


def _match_raises_value(problem: Problem, student_text: str) -> str | None:
    raise ValueError("주입한 표 오류")


_FAILURES: list[tuple[str, Any, str]] = [
    ("record_eval", _record_raises_db, "OperationalError"),
    ("record_eval", _record_raises_os, "ConnectionRefusedError"),
    ("match_misconception", _match_raises_value, "ValueError"),
]


@pytest.mark.parametrize(
    ("target", "replacement", "type_name"), _FAILURES, ids=[f[2] for f in _FAILURES]
)
def test_t2_failure_keeps_response(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    target: str,
    replacement: Any,
    type_name: str,
) -> None:
    """기록·매칭이 잡는 종류로 실패하면 응답은 200 그대로 · 경고에 예외 타입명(학생 문장은 없음)."""
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.delenv(T1_FLAG_ENV, raising=False)
    if target == "record_eval":
        monkeypatch.setattr(store, "record_eval", replacement)
    else:
        monkeypatch.setattr(api, "match_misconception", replacement)
    r = client.post("/golden/session", json={"nickname": f"t2-fail-{uuid.uuid4().hex[:6]}"})
    session_id = r.json()["session_id"]
    student_text = "학생비밀문장"
    with caplog.at_level(logging.WARNING, logger=api.__name__):
        r = client.post(
            "/golden/answer",
            json={"session_id": session_id, "problem_id": "LF-01", "text": student_text},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "tutor_turn" and body["turn"] == 1
    failures = [rec for rec in caplog.records if "golden T2 매칭 실패" in rec.getMessage()]
    assert len(failures) == 1  # 주입이 실제로 실패 경로를 밟았다
    message = failures[0].getMessage()
    assert type_name in message and "problem=LF-01" in message
    assert student_text not in message and body["message"] not in message
