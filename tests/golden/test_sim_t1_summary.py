"""S23 T1 집계(`golden.sim.t1_summary`) 테스트 — 실패 유형 분류 · 실행 기록 대조 · 전후 비교(F-01).

가짜 모드 스모크는 루브릭 실패가 0건이라(고정 대본) 실패 경로를 재지 못한다.
그래서 유출 출처 3종·발문 없음을 합성 세션으로 만들어 각 분기를 밟는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from golden.sim import t1_summary as ts

# 합성 문항 2개 — 정답 · 문제 본문
# LF-A: 정답 -12가 문제 본문에 없다 / LF-B: 정답 -12가 문제 본문에 있다(문제 본문 토큰 유출 유형)
ANSWERS = {
    "LF-A": ("-12", "f(x)=-3x+3일 때 f(5)의 값을 구하시오."),
    "LF-B": ("-12", "y=-12x+5의 기울기를 구하시오."),
}

SECRET = "비밀문장표지"  # 출력에 문장이 새지 않는지 볼 표지


def _turn(
    n: int, student: str, tutor: str, kind: str = "tutor_turn", correct: bool = False
) -> dict[str, Any]:
    return {"n": n, "student": student, "tutor": tutor, "kind": kind, "correct": correct}


def _session(persona: str, problem_id: str, turns: list[dict[str, Any]]) -> dict[str, Any]:
    return {"persona": persona, "problem_id": problem_id, "turns": turns, "http_status": 200}


def _rows() -> list[dict[str, Any]]:
    """유형별 되묻기 1건씩 + 통과 되묻기 + 정답 세션."""
    return [
        # 새로 말함: 학생은 3이라 했는데 튜터가 정답 -12를 말한다
        _session(
            "P2",
            "LF-A",
            [
                _turn(1, "3", f"{SECRET} 답은 -12야. 왜 그럴까?"),
                _turn(2, "-12", "맞아요", "graded", True),
            ],
        ),
        # 학생 답 되받음: 학생이 -12라고 했는데(틀린 판정 상황 가정) 튜터가 그 값을 되받는다
        _session("P3", "LF-A", [_turn(1, "-12 아님?", "-12라고 했구나. 어디서 나왔어?")]),
        # 문제 본문 토큰: 문제에 -12가 있다
        _session("P3", "LF-B", [_turn(1, "5", "식 y=-12x+5에서 x 앞의 수는 뭘까?")]),
        # 발문 없음(유출 아님)
        _session(
            "P4",
            "LF-A",
            [_turn(1, "몰라", "x 자리에 5를 넣어 봐."), _turn(2, "-12", "맞아요", "graded", True)],
        ),
        # 통과(유출 없음 · 물음표 있음)
        _session(
            "P4",
            "LF-A",
            [
                _turn(1, "몰라", "x 자리에 5를 넣으면 어떻게 될까?"),
                _turn(2, "-12", "맞아요", "graded", True),
            ],
        ),
    ]


# ──────────────────────────────────────────────────────────────────────
# 실패 유형 분류
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("leak", "origin", "passed", "has_prompt", "expected"),
    [
        (True, "new", False, True, ts.FAIL_LEAK_NEW),
        (True, "student_echo", False, True, ts.FAIL_LEAK_ECHO),
        (True, "problem_text", False, False, ts.FAIL_LEAK_STEM),  # 유출이 발문 없음보다 먼저다
        (True, "unknown", False, True, ts.FAIL_LEAK_UNKNOWN),
        (False, "none", False, False, ts.FAIL_NO_PROMPT),
        (False, "none", True, True, None),
    ],
)
def test_fail_type_maps_each_branch(
    leak: bool, origin: str, passed: bool, has_prompt: bool, expected: str | None
) -> None:
    assert ts.fail_type(leak, origin, passed, has_prompt) == expected


def test_fail_type_refuses_unknown_failure_reason() -> None:
    # 유출도 아니고 발문도 있는데 실패 — 평가기 규칙이 바뀐 것이다. 조용히 넘기지 않는다
    with pytest.raises(ts.SummaryError):
        ts.fail_type(False, "none", False, True)


# ──────────────────────────────────────────────────────────────────────
# 집계
# ──────────────────────────────────────────────────────────────────────


def test_summarize_rows_counts_each_failure_type_once() -> None:
    summary = ts.summarize_rows(_rows(), ANSWERS)
    assert summary["tutor_turns"] == 5
    assert summary["rubric_failed_turns"] == 4
    assert summary["fail_types"] == {
        ts.FAIL_LEAK_NEW: 1,
        ts.FAIL_LEAK_ECHO: 1,
        ts.FAIL_LEAK_STEM: 1,
        ts.FAIL_NO_PROMPT: 1,
    }
    # 동수면 이름순(결정론) — 네 유형이 1건씩이라 이름순 앞 3개
    assert summary["top3"] == sorted(summary["fail_types"])[:3]
    assert summary["leak_sessions_by_origin"] == {
        "new": 1,
        "unknown": 0,
        "problem_text": 1,
        "student_echo": 1,
    }
    assert summary["new_leak_problems"] == {"LF-A": 1}


def test_summarize_rows_ranks_by_count_first() -> None:
    rows = _rows() + [_session("P2", "LF-A", [_turn(1, "3", "x에 5를 넣어 봐.")]) for _ in range(2)]
    summary = ts.summarize_rows(rows, ANSWERS)
    assert summary["fail_types"][ts.FAIL_NO_PROMPT] == 3
    assert summary["top3"][0] == ts.FAIL_NO_PROMPT


def test_session_leak_origin_takes_the_heaviest_turn() -> None:
    # 한 세션에 되받음 1번 + 새로 말함 1번 → 그 세션은 "new"로 센다
    row = _session(
        "P3",
        "LF-A",
        [_turn(1, "-12 아님?", "-12라고 했구나. 왜?"), _turn(2, "3", "답은 -12인데 왜일까?")],
    )
    summary = ts.summarize_rows([row], ANSWERS)
    assert summary["leak_sessions_by_origin"]["new"] == 1
    assert summary["leak_sessions_by_origin"]["student_echo"] == 0


def test_per_persona_m2_uses_metrics_definition() -> None:
    summary = ts.summarize_rows(_rows(), ANSWERS)
    p4 = summary["per_persona"]["P4"]
    # P4 두 세션 모두 되묻기 1번 뒤 정답 → 평균 1.0
    assert p4 == {
        "sessions": 2,
        "to_correct": 2,
        "m2": 1.0,
        "tutor_turns": 2,
        "rubric_failed_turns": 1,
    }
    assert summary["per_persona"]["P3"]["m2"] is None  # 정답 세션 없음 → None(0이 아니다)


def test_summarize_rows_refuses_unknown_problem() -> None:
    with pytest.raises(ts.SummaryError):
        ts.summarize_rows([_session("P2", "LF-ZZ", [])], ANSWERS)


def test_summary_output_carries_no_utterance_text() -> None:
    # 학생·튜터 문장은 출력에 나가지 않는다(숫자·ID·페르소나만)
    dumped = json.dumps(ts.summarize_rows(_rows(), ANSWERS), ensure_ascii=False)
    assert SECRET not in dumped
    assert "왜 그럴까" not in dumped


def test_address_word_counted_without_text() -> None:
    # '학생' 호칭 되묻기만 센다 — S14 LATER 개정 후보의 전후 비교용
    rows = [
        _session(
            "P2",
            "LF-A",
            [_turn(1, "3", "학생이 직접 써 볼래요?"), _turn(2, "4", "어디서 막혔을까?")],
        ),
    ]
    summary = ts.summarize_rows(rows, ANSWERS)
    assert summary["address_student_turns"] == 1
    assert "직접 써" not in json.dumps(summary, ensure_ascii=False)


def test_answer_table_covers_all_golden_problems() -> None:
    table = ts.answer_table()
    assert len(table) == 30
    assert all(answer and stem for answer, stem in table.values())


# ──────────────────────────────────────────────────────────────────────
# 실행 기록 읽기 — 이번 실행 것인지 대조
# ──────────────────────────────────────────────────────────────────────


def _write_run(
    run_dir: Path,
    rows: list[dict[str, Any]],
    *,
    mode: str = "live",
    planned: int | None = None,
    report_sessions: int | None = None,
    m1: float = 0.0,
    m3: float = 0.0,
    personas: list[str] | None = None,
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / ts.SESSIONS_NAME).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    n = len(rows) if planned is None else planned
    meta = {
        "date": "2026-11-23",
        "mode": mode,
        "planned_sessions": n,
        "count_sessions": n,
        "personas": personas or ["P2", "P3", "P4"],
        "leak_undecidable_sessions": 0,
        "degraded_tutor_turns": 0,
    }
    (run_dir / ts.META_NAME).write_text(json.dumps(meta), encoding="utf-8")
    report = {
        "date": "2026-11-23",
        "sessions": len(rows) if report_sessions is None else report_sessions,
        "mode": mode,
        "M1": {"value": m1, "threshold": "0%", "pass": m1 == 0},
        "M2": {"value": 1.0, "threshold": "1.5~3.0", "pass": False},
        "M3": {"value": m3, "threshold": "<1%", "pass": m3 < 0.01},
        "M4": {"value": 0, "threshold": "0", "pass": True},
        "M5": {"value": 0, "threshold": "0", "pass": True},
        "exit_code": 0,
    }
    name = ts.REPORT_LIVE if mode == "live" else ts.REPORT_FAKE
    (run_dir / name).write_text(json.dumps(report), encoding="utf-8")
    return run_dir


def _golden_rows() -> list[dict[str, Any]]:
    """실제 골든 문항 ID로 만든 세션 — summarize()가 문항 표를 실제로 읽게 한다."""
    answer, _stem = ts.answer_table()["LF-01"]
    return [
        _session(
            "P2",
            "LF-01",
            [_turn(1, "3", "x에 넣으면 어떻게 될까?"), _turn(2, answer, "맞아요", "graded", True)],
        ),
        _session("P3", "LF-01", [_turn(1, "3", "x에 넣어 봐.")]),
    ]


def test_load_run_refuses_partial_run(tmp_path: Path) -> None:
    run = _write_run(tmp_path / "r", _golden_rows(), planned=120)
    with pytest.raises(ts.SummaryError, match="멈췄거나"):
        ts.load_run(run)


def test_load_run_refuses_missing_meta(tmp_path: Path) -> None:
    run = _write_run(tmp_path / "r", _golden_rows())
    (run / ts.META_NAME).unlink()
    with pytest.raises(ts.SummaryError, match="끝나지 않았다"):
        ts.load_run(run)


def test_load_run_refuses_report_from_other_run(tmp_path: Path) -> None:
    run = _write_run(tmp_path / "r", _golden_rows(), report_sessions=720)
    with pytest.raises(ts.SummaryError, match="세션 수"):
        ts.load_run(run)


def test_load_run_reads_only_the_report_of_its_mode(tmp_path: Path) -> None:
    # 가짜 실행 폴더에 실제 실행 보고서가 남아 있어도 가짜 보고서만 읽는다
    run = _write_run(tmp_path / "r", _golden_rows(), mode="fake")
    (run / ts.REPORT_LIVE).write_text(json.dumps({"sessions": 999}), encoding="utf-8")
    _rows_read, _meta, _report, name = ts.load_run(run)
    assert name == ts.REPORT_FAKE


def test_load_run_refuses_unknown_mode(tmp_path: Path) -> None:
    run = _write_run(tmp_path / "r", _golden_rows())
    meta = json.loads((run / ts.META_NAME).read_text(encoding="utf-8"))
    meta["mode"] = "mixed"
    (run / ts.META_NAME).write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ts.SummaryError, match="mode"):
        ts.load_run(run)


def test_load_run_refuses_empty_record(tmp_path: Path) -> None:
    run = _write_run(tmp_path / "r", [], planned=0)
    with pytest.raises(ts.SummaryError, match="0개"):
        ts.load_run(run)


# ──────────────────────────────────────────────────────────────────────
# 전후 비교
# ──────────────────────────────────────────────────────────────────────


def test_compare_keeps_when_m1_zero_and_m3_under_one_percent(tmp_path: Path) -> None:
    before = ts.summarize(_write_run(tmp_path / "b", _golden_rows(), m1=0.0, m3=0.0))
    after = ts.summarize(_write_run(tmp_path / "a", _golden_rows(), m1=0.0, m3=0.0099))
    result = ts.compare(before, after)
    assert result["m1_m3_kept"] is True
    assert result["revert_required"] is False


@pytest.mark.parametrize(("m1", "m3"), [(0.0014, 0.0), (0.0, 0.01)])
def test_compare_requires_revert_when_after_breaks_contract(
    tmp_path: Path, m1: float, m3: float
) -> None:
    before = ts.summarize(_write_run(tmp_path / "b", _golden_rows()))
    after = ts.summarize(_write_run(tmp_path / "a", _golden_rows(), m1=m1, m3=m3))
    result = ts.compare(before, after)
    assert result["m1_m3_kept"] is False
    assert result["revert_required"] is True
    assert "되돌린다" in ts.render_markdown(result)


def test_compare_refuses_different_run_conditions(tmp_path: Path) -> None:
    before = ts.summarize(_write_run(tmp_path / "b", _golden_rows()))
    after = ts.summarize(_write_run(tmp_path / "a", _golden_rows(), personas=["P2"]))
    with pytest.raises(ts.SummaryError, match="조건"):
        ts.compare(before, after)


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _write_run(tmp_path / "g", _golden_rows())
    out = tmp_path / "s.json"
    assert ts.main(["summarize", "--run-dir", str(good), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["t1"]["tutor_turns"] == 2
    md = tmp_path / "c.md"
    assert (
        ts.main(["compare", "--before", str(good), "--after", str(good), "--out-md", str(md)]) == 0
    )
    assert "| M1 |" in md.read_text(encoding="utf-8")
    assert ts.main(["summarize", "--run-dir", str(tmp_path / "없음")]) == 2
    assert "T1_SUMMARY_REFUSED" in capsys.readouterr().err
