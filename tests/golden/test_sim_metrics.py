"""S19 메트릭(`golden.sim.metrics`) 단위 테스트 — 순수 함수만(DB·LLM 없음).

- M1 유출 판정 복사본이 옛 `pedagogical_rubric.detect_answer_leakage`와 같은 출력인지 나란히 대조한다
  (옛 모듈은 LEGACY_MANIFEST라 골든 코드는 import하지 않고 복사했다 — 테스트에서만 옛 자리를 부른다).
- M5 렌더 깨짐 정규식은 사유마다 반례(깨진 것)와 대조군(멀쩡한 것)을 함께 둔다.
- M3 "시뮬레이터가 아는 턴"과 집계(compute)의 차단·경고 구분.
"""

from __future__ import annotations

from typing import Any

import pytest

from golden.sim import metrics
from whymath_backend.harness.pedagogical_rubric import detect_answer_leakage as old_detect

# ── M1: 복사본 ↔ 옛 함수 대조 ────────────────────────────────────────────────

# (응답, 정답) — S21 특성화 입력(tests/golden/characterization/test_t1_rubric.py)의 정답·발화 모양 +
# 경계 사례(단어 경계·LaTeX·전각·1글자·흔한 토큰·식 정답). 기대값은 옛 함수가 정한다.
_LEAK_CASES: list[tuple[str, str]] = [
    ("f(5)는 -12라고 말했군요. 어떤 식을 세웠는지 말해 볼래요?", "-12"),
    ("이번 문제의 답은 -8이었어요. 다음 문제에서 다시 해 봐요.", "-8"),
    ("x 자리에 2를 넣은 식을 계산한 값으로 -4를 말했군요.", "4"),
    ("\\(f(-1)\\)이라는 표시는 \\(f(x)\\)에서 \\(x\\) 자리에 어떤 수를 넣으라는 뜻인지", "0"),
    ("기울기를 $-\\frac{2}{3}$라고 구했군요.", "-3/2"),
    ("분모에 x의 값의 증가량을 넣어 $6\\div(-9)$까지 식을 세운 셈이군요.", "-3/2"),
    ("어느 부분이 막히는지 한 가지만 말해 줄래? x 자리에 3을 넣으면", "-8"),
    ("−3×5를 15라고 계산했군요.", "-12"),
    ("값이 -120이 되나요?", "-12"),
    ("값이 -12.5가 되나요?", "-12"),
    ("값은 −12일까요?", "-12"),
    ("값은 －１２일까요?", "-12"),
    ("식은 $y = 2x + 1$ 이에요", "2*x + 1"),
    ("식은 2*x + 1 이에요", "2*x + 1"),
    ("답은 3이야", "3"),
    ("정답이야", "정답"),
    ("3/2라고?", "3/2"),
    ("", "-12"),
]


@pytest.mark.parametrize(("response", "answer"), _LEAK_CASES)
def test_leak_copy_matches_old_function(response: str, answer: str) -> None:
    assert (
        metrics.detect_answer_leakage(response, answer).value == old_detect(response, answer).value
    )


def test_leak_cases_cover_all_three_verdicts() -> None:
    # 대조 표가 세 상태를 모두 밟는다(한 상태만 있는 대조는 공허하다)
    seen = {old_detect(r, a).value for r, a in _LEAK_CASES}
    assert seen == {"leaked", "clean", "undecidable"}


def test_session_leak_ignores_graded_feedback() -> None:
    # 판정 뒤 피드백(graded)은 정답을 알려 주는 계약 문장 — 유출로 세지 않는다
    turns = [
        {"n": 1, "tutor": "어디가 막혔어?", "kind": "tutor_turn"},
        {"n": 2, "tutor": "이번 문제의 답은 -12였어요.", "kind": "graded"},
    ]
    assert metrics.session_leak(turns, "-12") is metrics.LeakageVerdict.clean
    turns[0]["tutor"] = "답은 -12야. 맞지?"
    assert metrics.session_leak(turns, "-12") is metrics.LeakageVerdict.leaked


def test_session_leak_short_answer_is_undecidable_not_clean() -> None:
    # 1글자 정답은 판정 유보 — clean으로 접지 않는다(모른다 ≠ 아니다)
    turns = [{"n": 1, "tutor": "3을 넣으면?", "kind": "tutor_turn"}]
    assert metrics.session_leak(turns, "3") is metrics.LeakageVerdict.undecidable


# ── M5: 렌더 깨짐 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "reasons"),
    [
        ("기울기는 $\\frac{1}{2}$ 일까?", []),  # 대조군: 짝 맞는 $ · 정상 \frac
        ("\\$5 는 돈 표시야", []),  # 대조군: 이스케이프된 $는 세지 않는다
        ("$x$절편과 $y$절편", []),  # 대조군: $ 4개
        ("$\\frac{a+{b}}{2}$", []),  # 대조군: 안쪽 중괄호 1단계
        ("기울기는 $\\frac{1}{2} 일까?", ["짝 안 맞는 $"]),
        ("$\\frac{1}2$", ["깨진 \\frac"]),
        ("$\\frac 12$", ["깨진 \\frac"]),
        ("$\\frac{1}{2}$ 와 $\\frac{3}$", ["깨진 \\frac"]),
        ("`y=2x` 를 봐", ["백틱"]),
        ("$x `", ["짝 안 맞는 $", "백틱"]),
    ],
)
def test_render_problems(text: str, reasons: list[str]) -> None:
    assert metrics.render_problems(text) == reasons


def test_session_render_broken_checks_graded_feedback_too() -> None:
    turns = [
        {"n": 1, "tutor": "어디가 막혔어?", "kind": "tutor_turn"},
        {"n": 2, "tutor": "답은 `3`이었어요.", "kind": "graded"},
    ]
    assert metrics.session_render_broken(turns) is True


# ── M3: 시뮬레이터가 아는 턴 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("persona", "n", "forced", "expected"),
    [
        ("P5", 1, None, True),
        ("P5", 2, None, True),
        ("P3", 1, "15", False),
        ("P3", 3, "15", False),
        ("P2", 1, "15", False),
        ("P2", 2, "15", None),  # P2 둘째 입력부터는 "다시 시도" — 모른다
        ("P2", 1, None, None),
        ("P1", 1, None, None),
        ("P8", 1, None, None),
        ("P7", 1, None, None),
    ],
)
def test_expected_correct(persona: str, n: int, forced: str | None, expected: bool | None) -> None:
    assert metrics.expected_correct(persona, n, forced) is expected


def _session(persona: str = "P5", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "persona": persona,
        "problem_id": "LF-01",
        "turns": [
            {"n": 1, "student": "-12", "tutor": "맞았어요.", "kind": "graded", "correct": True}
        ],
        "forced_answer": None,
        "injected_op": None,
        "elapsed_s": 0.1,
        "http_status": 200,
        "leak": False,
        "render_broken": False,
    }
    base.update(over)
    return base


def test_compute_all_green() -> None:
    m = metrics.compute([_session(), _session("P1")])
    assert [m[k]["pass"] for k in metrics.BLOCKING] == [True] * 4
    assert set(m["M1"]) == {"value", "threshold", "pass"}


def test_compute_empty_is_not_a_pass() -> None:
    # 세션 0개는 공허한 통과가 아니다
    assert metrics.blocking_failures(metrics.compute([])) == ["M1", "M3", "M4", "M5"]


@pytest.mark.parametrize(
    ("override", "failed"),
    [
        ({"leak": True}, "M1"),
        ({"http_status": 500}, "M4"),
        ({"http_status": None}, "M4"),
        ({"render_broken": True}, "M5"),
        (
            {
                "turns": [
                    {"n": 1, "student": "-12", "tutor": "x", "kind": "graded", "correct": False}
                ]
            },
            "M3",
        ),
    ],
)
def test_each_blocking_metric_trips(override: dict[str, Any], failed: str) -> None:
    m = metrics.compute([_session(), _session(**override)])
    assert metrics.blocking_failures(m) == [failed]


def test_m2_out_of_range_warns_but_does_not_block() -> None:
    # P5가 0턴에 정답 → M2 평균 0 → 범위(1.5~3.0) 밖이지만 차단 아님
    m = metrics.compute([_session()])
    assert m["M2"]["value"] == 0 and m["M2"]["pass"] is False
    assert "M2" not in metrics.blocking_failures(m)


def test_worst_persona_and_slowest_problem() -> None:
    sessions = [
        _session("P1", elapsed_s=0.1),
        _session("P7", problem_id="LF-02", elapsed_s=5.0, http_status=None),
        _session("P5", problem_id="LF-03", elapsed_s=1.0),
    ]
    assert metrics.worst_persona(sessions) == "P7"
    assert metrics.slowest_problem(sessions) == "LF-02"
    assert metrics.worst_persona([]) is None and metrics.slowest_problem([]) is None
