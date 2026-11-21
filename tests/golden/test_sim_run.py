"""S19 러너(`golden.sim.run`) 테스트 — 가짜 모드(GOLDEN_FAKE_LLM=1 · conftest)로 골든 API를 HTTP로 밟는다.

지시서 S19 할 일 7: 가짜 모드 2페르소나 × 2문항 → jsonl 4줄 · report 필드 전부 · exit code
(치명 위반 주입 시 1 — M4 강제 1건 주입 픽스처). 그 밖에 비용 가드(720)·즉시 기록·시간 초과를 동결한다.
DB는 다른 골든 e2e 테스트와 같은 Postgres(WHYMATH_DATABASE_URL)를 쓴다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from golden import api, problems
from golden.sim import errors, run, student

_SESSION_KEYS = {
    "persona",
    "problem_id",
    "turns",
    "forced_answer",
    "injected_op",
    "elapsed_s",
    "http_status",
    "leak",
    "render_broken",
}
_TURN_KEYS = {"n", "student", "tutor", "kind", "correct"}
_REPORT_KEYS = {
    "date",
    "sessions",
    "mode",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "worst_persona",
    "slowest_problem",
    "exit_code",
}


def _main(tmp_path: Path, *extra: str) -> int:
    """CLI를 가짜 모드로 부른다(2문항)."""
    argv = ["--out-dir", str(tmp_path), "--date", "2026-11-20", "--problems", "2", *extra]
    return run.main(argv, environ={"GOLDEN_FAKE_LLM": "1"})


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fake_two_personas_two_problems(tmp_path: Path) -> None:
    code = _main(tmp_path, "--personas", "P2,P5")
    assert code == 0
    rows = _lines(tmp_path / run.SESSIONS_FILE)
    assert len(rows) == 4
    for row in rows:
        assert set(row) == _SESSION_KEYS
        assert row["http_status"] == 200 and row["turns"]
        assert all(set(t) == _TURN_KEYS for t in row["turns"])
        assert row["turns"][-1]["kind"] == "graded"
    assert [(r["persona"], r["problem_id"]) for r in rows] == [
        ("P2", "LF-01"),
        ("P2", "LF-02"),
        ("P5", "LF-01"),
        ("P5", "LF-02"),
    ]
    # P2는 주입기 답(오답) → 튜터 1턴 → 정답 · P5는 첫 입력 정답
    p2 = rows[0]
    assert (
        p2["forced_answer"]
        and p2["injected_op"]
        and p2["turns"][0]["student"] == p2["forced_answer"]
    )
    assert [t["kind"] for t in p2["turns"]] == ["tutor_turn", "graded"] and p2["turns"][1][
        "correct"
    ]
    assert rows[2]["forced_answer"] is None and rows[2]["turns"][0]["correct"] is True

    assert not (tmp_path / run.REPORT_LIVE).exists()
    report = json.loads((tmp_path / run.REPORT_FAKE).read_text(encoding="utf-8"))
    assert set(report) == _REPORT_KEYS
    assert report["mode"] == "fake" and report["sessions"] == 4 and report["exit_code"] == 0
    for name in ("M1", "M2", "M3", "M4", "M5"):
        assert set(report[name]) == {"value", "threshold", "pass"}
    assert report["M4"]["value"] == 0 and report["M5"]["value"] == 0
    assert report["M3"]["value"] == 0.0  # 아는 턴 = P2 첫 입력 2 + P5 2
    meta = json.loads((tmp_path / run.META_FILE).read_text(encoding="utf-8"))
    assert meta["count_m3_known_turns"] == 4 and meta["planned_sessions"] == 4
    assert (tmp_path / run.ERRORS_FILE).read_text(encoding="utf-8") == ""


async def _tutor_crash(*_: object, **__: object) -> object:
    raise RuntimeError("주입: 튜터 내부 예외")


def test_injected_m4_crash_makes_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # M4 강제 1건: P1의 첫 오답에서 튜터가 터진다 → 실학생처럼 HTTP 500 → 크래시 1건 → exit 1
    monkeypatch.setattr(api.tutor, "ask", _tutor_crash)
    # P5는 첫 입력이 정답이라 튜터를 부르지 않는다 — M3를 잴 턴(2)을 대고 M4만 떨어지게 한다
    code = _main(tmp_path, "--personas", "P1,P5")
    assert code == 1
    rows = _lines(tmp_path / run.SESSIONS_FILE)
    assert [r["http_status"] for r in rows] == [500, 200, 200]
    assert rows[0]["problem_id"] == "LF-01"
    report = json.loads((tmp_path / run.REPORT_FAKE).read_text(encoding="utf-8"))
    assert report["exit_code"] == 1 and report["M4"] == {
        "value": 1,
        "threshold": "0",
        "pass": False,
    }
    meta = json.loads((tmp_path / run.META_FILE).read_text(encoding="utf-8"))
    assert meta["skipped_sessions"] == 1 and meta["blocking_failures"] == ["M4"]
    err = _lines(tmp_path / run.ERRORS_FILE)
    assert err[0]["error_type"] == "HttpStatusError" and "500" in err[0]["detail"]


def test_student_timeout_counts_as_m4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(*_: object, **__: object) -> str:
        await asyncio.sleep(1.0)
        return "3"

    monkeypatch.setattr(run, "STUDENT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(student, "reply_async", slow)
    assert _main(tmp_path, "--personas", "P5") == 1
    rows = _lines(tmp_path / run.SESSIONS_FILE)
    assert rows[0]["http_status"] is None  # 응답이 아니라 시간 초과로 멈췄다
    assert _lines(tmp_path / run.ERRORS_FILE)[0]["error_type"] == "TimeoutError"


def test_lines_are_written_before_an_unexpected_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 러너 자체의 결함(이름 없는 예외)은 잡지 않고 멈춘다 — 그래도 앞 세션 줄은 디스크에 남아 있다
    real = student.reply_async
    calls = {"n": 0}
    seen: dict[str, int] = {}

    async def flaky(
        persona: str,
        problem: problems.Problem,
        history: Sequence[Mapping[str, object]],
        *a: Any,
        **k: Any,
    ) -> str:
        if problem["id"] == "LF-02":
            # 실행 도중(파일이 아직 열려 있을 때) 디스크에 앞 세션 줄이 이미 있어야 한다
            seen["lines"] = len(_lines(tmp_path / run.SESSIONS_FILE))
            raise ZeroDivisionError("주입")
        calls["n"] += 1
        return await real(persona, problem, history, *a, **k)

    monkeypatch.setattr(student, "reply_async", flaky)
    with pytest.raises(ZeroDivisionError):
        _main(tmp_path, "--personas", "P5")
    rows = _lines(tmp_path / run.SESSIONS_FILE)
    assert len(rows) == 1 and rows[0]["problem_id"] == "LF-01" and calls["n"] == 1
    assert seen == {"lines": 1}


def test_full_720_requires_sim_full() -> None:
    assert run.resolve_sessions(720, {}) == (120, run.resolve_sessions(720, {})[1])
    assert run.resolve_sessions(720, {})[1] is not None
    assert run.resolve_sessions(720, {"SIM_FULL": "0"})[0] == 120
    assert run.resolve_sessions(720, {"SIM_FULL": "1"}) == (720, None)
    assert run.resolve_sessions(120, {}) == (120, None)


def test_cli_rejects_other_session_counts(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _main(tmp_path, "--sessions", "500")


@pytest.mark.parametrize(
    ("sessions", "personas", "n", "rounds", "per"),
    [
        (120, ["P1", "P2", "P5", "P7"], 30, 1, 30),
        (120, list(student.PERSONAS), 30, 1, 15),
        (720, list(student.PERSONAS), 30, 3, 30),
        (120, ["P2", "P5"], 2, 30, 2),
    ],
)
def test_make_plan(sessions: int, personas: list[str], n: int, rounds: int, per: int) -> None:
    plan = run.make_plan(sessions, personas, n)
    assert (plan.rounds, plan.per_round) == (rounds, per)
    assert plan.sessions <= sessions


def test_make_plan_rejects_unknown_persona() -> None:
    with pytest.raises(ValueError):
        run.make_plan(120, ["P9"], 30)


def test_nickname_shape() -> None:
    assert run.nickname("P3", 2) == "sim-P3-2"


def test_max_inputs_matches_api() -> None:
    assert run.MAX_INPUTS == api.MAX_TUTOR_TURNS + 1


def test_p3_gets_a_wrong_injected_answer_for_every_problem() -> None:
    # P3는 주입기 답 없이는 돌 수 없다 — 30문항 × 3회차 모두 답이 나오고, 그 답은 언제나 오답이다
    for problem in problems.load_problems():
        for round_no in (1, 2, 3):
            wrong = run.pick_injection(problem, "P3", round_no)
            assert wrong is not None, problem["id"]
            assert wrong.op_code in errors.INJECTABLE_OPS
            assert run.pick_injection(problem, "P3", round_no) == wrong  # 결정적
    assert run.pick_injection(problems.load_problems()[0], "P1", 1) is None


def test_degraded_tutor_turns_are_counted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 튜터 LLM이 실패해 대체 문장(degraded)만 오가면 M1·M5가 깨끗해도 튜터를 잰 게 아니다 — 횟수를 남긴다
    async def degraded(*_: object, **__: object) -> api.tutor.TutorReply:
        return api.tutor.TutorReply(message="대체 문장이야. 어디가 막혔어?", degraded=True)

    monkeypatch.setattr(api.tutor, "ask", degraded)
    assert _main(tmp_path, "--personas", "P1,P5") == 0
    meta = json.loads((tmp_path / run.META_FILE).read_text(encoding="utf-8"))
    assert meta["degraded_tutor_turns"] == 6  # P1 × 2문항 × 되묻기 3턴 · P5는 튜터 0턴


def test_crash_leaves_no_stale_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """러너가 도중에 죽으면 같은 폴더의 지난 보고서가 남지 않는다(S20 실측 — 46세션에서 죽은 실행 옆에
    앞 실행의 120세션 보고서가 남아 이번 숫자처럼 보였다)."""
    for name in (run.REPORT_LIVE, run.REPORT_FAKE, run.META_FILE):
        (tmp_path / name).write_text('{"sessions": 120}', encoding="utf-8")

    async def broken(*_: object, **__: object) -> str:
        raise ZeroDivisionError("주입: 러너가 잡지 않는 예외")

    monkeypatch.setattr(run.student, "reply_async", broken)
    with pytest.raises(ZeroDivisionError):
        _main(tmp_path, "--personas", "P2")
    for name in (run.REPORT_LIVE, run.REPORT_FAKE, run.META_FILE):
        assert not (tmp_path / name).exists(), name
