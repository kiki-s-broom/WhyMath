"""P3-44 S1 — 보강 은행 4개 개념의 오개념 연결 검증 규칙 회귀 테스트(hermetic·LLM 0).

설계 `docs/reviews/p3_44_new_frames_design_2026-10-16.md` §4: 판정기 `_misconception_rules`에 M0673(곡선 밖의
점에서 그은 접선)·M0674 개수형(롤의 정리 혼동)·M0676(점만 찍어 잇기)·M0678(속도 부호 무시) 절을 더한다.
규칙 id는 기존 `M-link-procedure`를 재사용한다(자격 측정 투표 집합은 바뀌지 않는다).

이 파일이 못 박는 것:
① 정상 표본(선택지 값이 오개념 절차의 산출임을 SymPy로 확인한 문항)은 GREEN이다.
② 변별 주입 — 라벨을 무관 오답·정답 선지에 붙이거나, 오개념 상황이 생기지 않게 문항을 바꾸거나, 해설의
   절차 문장을 지우거나, 발문을 못 읽게 만들면 RED다. 주입마다 표본이 실제로 바뀌었는지 단언한다.
③ 소급 — 기존 승인 은행 두 개에는 새 절이 발화할 연결(M0673·M0676·M0678·개수형 M0674)이 없다.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import sympy

from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
    POST_QUALIFICATION_RULE_IDS,
    ShortcutProbe,
    probe_from_record,
    shortcut_violations,
)

_ROOT = Path(__file__).resolve().parents[4]
_RULE = "M-link-procedure"
x, t = sympy.symbols("x t")


def _rules(probe: ShortcutProbe) -> set[str]:
    return {v.rule for v in shortcut_violations(probe)}


def _inject(probe: ShortcutProbe, **changes: object) -> ShortcutProbe:
    """주입 — 실제로 바뀌었는지 단언한다(조용히 실패한 주입이 '검출'처럼 보이지 않게)."""
    mutated = dataclasses.replace(probe, **changes)  # type: ignore[arg-type]
    assert mutated != probe
    return mutated


# ── M0673 · 02-05 접선(곡선 밖의 점) ─────────────────────────────────────────
_F05 = -2 * x**3 + 3 * x**2 + 4 * x - 3
M0673_SLOPE = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-05]",
    question_text=(
        "점 (1, 46)에서 곡선 y = -2x^3 + 3x^2 + 4x - 3에 그은 접선은 하나뿐이다. "
        "이 접선의 기울기로 옳은 것은?"
    ),
    answer="-32",
    explanation="접점을 (t, f(t))라 하자.",
    choices=("-68", "-32", "-18", "4"),
    conditions=("-8*m**3 + 105*m**2 + 4296*m - 232192 = 0",),
    answer_map=(("m", "-32"),),
    distractors=((3, "M0673"),),
)
M0673_INTERCEPT = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-05]",
    question_text=(
        "점 (1, 60)에서 곡선 y = 2x^3 - x^2 - x - 3에 그은 접선은 하나뿐이다. "
        "이 접선의 y절편으로 옳은 것은?"
    ),
    answer="33",
    explanation="접점을 (t, f(t))라 하자.",
    choices=("-21", "27", "33", "57"),
    conditions=("-8*k**3 + 1393*k**2 - 92166*k + 1811997 = 0",),
    answer_map=(("k", "33"),),
    distractors=((3, "M0673"),),
)
M0673_VALUE = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-05]",
    question_text=(
        "점 (1, 69)에서 곡선 y = x^3 + x^2 + 4x - 1에 그은 접선은 하나뿐이다. "
        "이 접선의 방정식을 y = g(x)라 할 때, g(-2)의 값으로 옳은 것은?"
    ),
    answer="-6",
    explanation="접점을 (t, f(t))라 하자.",
    choices=("-13", "-6", "25", "42"),
    conditions=("-4*y**3 + 552*y**2 - 66672*y - 420768 = 0",),
    answer_map=(("y", "-6"),),
    distractors=((3, "M0673"),),
)


def test_m0673_fixture_values_are_procedure_outputs() -> None:
    """정상 표본의 연결 선지가 '주어진 점을 접점으로 삼은' 절차의 산출인지 SymPy로 독립 확인한다."""
    slope = sympy.diff(_F05, x).subs(x, 1)
    assert slope == 4 and M0673_SLOPE.choices[3] == "4"
    f2 = 2 * x**3 - x**2 - x - 3
    assert 60 - 1 * sympy.diff(f2, x).subs(x, 1) == 57
    f3 = x**3 + x**2 + 4 * x - 1
    assert 69 + sympy.diff(f3, x).subs(x, 1) * (-2 - 1) == 42


# ── M0674 개수형 · 02-06 평균값 정리 ─────────────────────────────────────────
_F06 = x**3 - 4 * x**2 + 5 * x + 2
M0674_COUNT = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-06]",
    question_text=(
        "함수 f(x) = x^3 - 4x^2 + 5x + 2에 대하여 열린구간 (-3, 2)에서 "
        "f'(c) = (f(2) - f(-3))/(2 - (-3))를 만족시키는 실수 c의 개수는?"
    ),
    answer="1",
    explanation="f'(x) = 3x^2 - 8x + 5이다.",
    choices=("0", "1", "2", "3"),
    conditions=("3*x**2 - 8*x - 11 = 0", "x > -3", "x < 2"),
    answer_kind="real_root_count",
    distractors=((2, "M0674"),),
)


def test_m0674_fixture_values_are_procedure_outputs() -> None:
    m = (_F06.subs(x, 2) - _F06.subs(x, -3)) / 5
    correct = [r for r in sympy.solve(sympy.diff(_F06, x) - m, x) if -3 < r < 2]
    rolle = [r for r in sympy.solve(sympy.diff(_F06, x), x) if -3 < r < 2]
    assert len(correct) == 1 and len(rolle) == 2


# ── M0676 · 02-08 그래프 개형(정수 점 · 영점) ────────────────────────────────
M0676_GRID = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-08]",
    question_text="삼차함수 f(x) = -4x^3 - 21x^2 - 18x - 3이 극댓값을 갖는 x좌표는?",
    answer="-1/2",
    explanation=(
        "f'(x) = -12x^2 - 42x - 18 = -6(x + 3)(2x + 1)이므로 f'(x) = 0의 근은 x = -3, -1/2이다. "
        "정수 x = -2, -1, 0에서 f(x)의 값은 -19, -2, -3이므로 정수인 점만 찍어 이으면 x = -1에서 "
        "가장 높아 보이지만, f'(-1) = 12 ≠ 0이므로 그 점은 극댓값을 갖는 x좌표가 아니다. "
        "따라서 극댓값을 갖는 x좌표는 -1/2이다."
    ),
    choices=("-3", "-1", "-1/2", "1/2"),
    conditions=("Derivative(-4*x**3 - 21*x**2 - 18*x - 3, x).doit() = 0",),
    answer_map=(("x", "-1/2"),),
    distractors=((1, "M0676"),),
)
M0676_ZERO = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-08]",
    question_text="함수 f(x) = -(x + 5)(x + 2)(x - 3)이 극댓값을 갖는 x좌표는?",
    answer="1",
    explanation=(
        "f(x) = -x^3 - 4x^2 + 11x + 30이다. f'(x) = -3x^2 - 8x + 11 = -(3x + 11)(x - 1)이다. "
        "영점 x = -5, -2, 3만 찍어 이으면 두 영점 -2, 3의 가운데 x = 1/2에서 가장 높아 보이지만, "
        "f'(1/2) = 25/4 ≠ 0이므로 그 점은 극댓값을 갖는 x좌표가 아니다. 따라서 극댓값을 갖는 x좌표는 1이다."
    ),
    choices=("-11/3", "-1", "1/2", "1"),
    conditions=("Derivative(-x**3 - 4*x**2 + 11*x + 30, x).doit() = 0",),
    answer_map=(("x", "1"),),
    distractors=((2, "M0676"),),
)
#: 변곡점 혼동 틀(설계 F3) — Kiki 결정(2026-10-17)으로 본선 제외. 절차로 인정하지 않으므로 RED여야 한다.
M0676_FLAT = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-08]",
    question_text="함수 f(x) = 3x^4 + 20x^3 + 48x^2 + 48x + 6이 극솟값을 갖는 x좌표는?",
    answer="-1",
    explanation=(
        "f'(x) = 12(x + 2)^2(x + 1)이다. x = -2의 좌우에서 f'(x)의 부호가 바뀌지 않으므로 극값이 "
        "아니다. x = -2는 변곡점이지 극값이 아니다. 따라서 구하는 x좌표는 -1이다."
    ),
    choices=("-2", "-1", "0", "1"),
    conditions=("Derivative(3*x**4 + 20*x**3 + 48*x**2 + 48*x + 6, x).doit() = 0",),
    answer_map=(("x", "-1"),),
    distractors=((0, "M0676"),),
)


def test_m0676_fixture_values_are_procedure_outputs() -> None:
    f1 = -4 * x**3 - 21 * x**2 - 18 * x - 3
    vals = {n: f1.subs(x, n) for n in range(-41, 42)}
    peaks = [n for n in range(-40, 41) if vals[n] > vals[n - 1] and vals[n] > vals[n + 1]]
    assert peaks == [-1]
    # 극대 x = 1을 둘러싼 영점 -2, 3의 가운데
    assert sympy.Rational(-2 + 3, 2) == sympy.Rational(1, 2)


# ── M0678 · 02-10 속도·가속도(속력을 속도로 놓음) ───────────────────────────
M0678_TIME = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-10]",
    question_text=(
        "수직선 위를 움직이는 점 P의 시각 t (t > 0)에서의 위치가 x = t^3 - 6t^2 - 18t + 5이다. "
        "점 P가 음의 방향으로 움직이면서 속력이 18이 되는 시각 t는?"
    ),
    answer="4",
    explanation="속도는 위치를 시각 t로 미분한 값이므로 v(t) = 3t^2 - 12t - 18이다.",
    choices=("2", "4", "6", "8"),
    conditions=("Derivative(t**3 - 6*t**2 - 18*t + 5, t).doit().subs(t, s) = -18", "s > 0"),
    answer_map=(("s", "4"),),
    distractors=((2, "M0678"),),
)
M0678_CONST = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-10]",
    question_text=(
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^3 + kt^2 + 3t이다 (k는 상수). "
        "t = 1에서 점 P가 음의 방향으로 움직이면서 속력이 10이 될 때, k의 값은?"
    ),
    answer="-8",
    explanation="속도는 위치를 시각 t로 미분한 값이므로 v(t) = 3t^2 + 2kt + 3이다.",
    choices=("-8", "-3", "2", "5"),
    conditions=("Derivative(t**3 + k*t**2 + 3*t, t).doit().subs(t, 1) = -10",),
    answer_map=(("k", "-8"),),
    distractors=((2, "M0678"),),
)
M0678_VALUE = ShortcutProbe(
    standard_code="[12미적Ⅰ-02-10]",
    question_text=(
        "수직선 위를 움직이는 점 P의 시각 t에서의 위치가 x = t^3 - 6t^2 + 1일 때, "
        "t = 2인 순간 점 P의 속도로 알맞은 것은?"
    ),
    answer="-12",
    explanation="속도는 위치를 시각 t로 미분한 값이므로 v(t) = 3t^2 - 12t이다.",
    choices=("-12", "-4", "4", "12"),
    conditions=("Derivative(t**3 - 6*t**2 + 1, t).doit().subs(t, 2) = y",),
    answer_map=(("y", "-12"),),
    distractors=((3, "M0678"),),
)


def test_m0678_fixture_values_are_procedure_outputs() -> None:
    v = sympy.diff(t**3 - 6 * t**2 - 18 * t + 5, t)
    assert [r for r in sympy.solve(v + 18, t) if r > 0] == [4]
    assert [r for r in sympy.solve(v - 18, t) if r > 0] == [6]
    k = sympy.Symbol("k")
    vk = sympy.diff(t**3 + k * t**2 + 3 * t, t).subs(t, 1)
    assert sympy.solve(vk + 10, k) == [-8] and sympy.solve(vk - 10, k) == [2]


_GREEN = {
    "M0673-slope": M0673_SLOPE,
    "M0673-intercept": M0673_INTERCEPT,
    "M0673-value": M0673_VALUE,
    "M0674-count": M0674_COUNT,
    "M0676-grid": M0676_GRID,
    "M0676-zero-mid": M0676_ZERO,
    "M0678-time": M0678_TIME,
    "M0678-const": M0678_CONST,
    "M0678-value": M0678_VALUE,
}


@pytest.mark.parametrize("name", sorted(_GREEN))
def test_honest_fixture_is_green(name: str) -> None:
    probe = _GREEN[name]
    assert [str(v) for v in shortcut_violations(probe) if v.rule == _RULE] == []


def _relabel(probe: ShortcutProbe, index: int) -> ShortcutProbe:
    mid = probe.distractors[0][1]
    return _inject(probe, distractors=((index, mid),))


def _correct_index(probe: ShortcutProbe) -> int:
    return probe.choices.index(probe.answer)


_RED: dict[str, ShortcutProbe] = {
    # ① 무관 오답 · ② 정답 선지에 라벨
    "M0673-unrelated": _relabel(M0673_SLOPE, 2),
    "M0673-correct": _relabel(M0673_SLOPE, _correct_index(M0673_SLOPE)),
    "M0673-intercept-unrelated": _relabel(M0673_INTERCEPT, 1),
    "M0673-value-unrelated": _relabel(M0673_VALUE, 0),
    # ④ 조건 위반 — 점이 곡선 위에 있다(f(1) = 2): M0673 상황이 생기지 않는다
    "M0673-on-curve": _inject(
        M0673_SLOPE,
        question_text=M0673_SLOPE.question_text.replace("점 (1, 46)", "점 (1, 2)"),
    ),
    # 절차 값(4)이 정답과 같은 문항 — 연결 선지는 절차 값 그대로지만 정답과 겹친다
    "M0673-procedure-equals-answer": _inject(M0673_SLOPE, answer="4"),
    # fail-closed — 발문을 못 읽는다(묻는 대상이 없음)
    "M0673-unreadable": _inject(
        M0673_SLOPE,
        question_text=M0673_SLOPE.question_text.replace(
            "이 접선의 기울기로 옳은 것은?", "옳은 것은?"
        ),
    ),
    "M0674-unrelated": _relabel(M0674_COUNT, 3),
    "M0674-correct": _relabel(M0674_COUNT, _correct_index(M0674_COUNT)),
    # 롤 값(2)이 정답과 같은 문항 — 연결 선지는 절차 값 그대로지만 정답과 겹친다(변별 없음)
    "M0674-rolle-equals-answer": _inject(M0674_COUNT, answer="2"),
    "M0674-unreadable": _inject(
        M0674_COUNT,
        question_text="함수 f(x)에 대하여 평균값 정리를 만족시키는 실수 c의 개수는?",
    ),
    "M0676-unrelated": _relabel(M0676_GRID, 0),
    "M0676-correct": _relabel(M0676_GRID, _correct_index(M0676_GRID)),
    "M0676-zero-unrelated": _relabel(M0676_ZERO, 1),
    # ③ 해설 절차 삭제
    "M0676-explanation-stripped": _inject(
        M0676_GRID,
        explanation="f'(x) = -6(x + 3)(2x + 1)이다. 따라서 극댓값을 갖는 x좌표는 -1/2이다.",
    ),
    # 발문 바꿔치기 — 극대·극소를 묻지 않는다
    "M0676-kind-not-asked": _inject(
        M0676_GRID,
        question_text="삼차함수 f(x) = -4x^3 - 21x^2 - 18x - 3이 극값을 갖는 x좌표 중 큰 값은?",
    ),
    # 정수 점 꼭대기(-1)가 정답과 같은 문항 — 절차 값 그대로지만 정답과 겹친다
    "M0676-procedure-equals-answer": _inject(M0676_GRID, answer="-1"),
    # 변곡점 틀(F3) — 결정으로 제외
    "M0676-flat-excluded": M0676_FLAT,
    "M0678-unrelated": _relabel(M0678_TIME, 3),
    "M0678-correct": _relabel(M0678_TIME, _correct_index(M0678_TIME)),
    "M0678-const-unrelated": _relabel(M0678_CONST, 3),
    # 우변이 양수(양의 방향 문항) — 정답 6, 연결 선지 4는 v = -18의 해. 부호 뒤집힌 식의 해라도
    # 학생이 '속력을 속도로' 놓는 상황이 아니다(우변 음수 요구 절이 없으면 통과해 버린다).
    "M0678-positive-rhs": _inject(
        M0678_TIME,
        conditions=("Derivative(t**3 - 6*t**2 - 18*t + 5, t).doit().subs(t, s) = 18", "s > 0"),
        answer="6",
        answer_map=(("s", "6"),),
        distractors=((1, "M0678"),),
    ),
    # 값 문항에서 속도가 양수(t = 5 → v = 15) — 연결 선지 -15는 -v이지만 '부호를 뗀' 값이 아니다
    "M0678-value-positive-velocity": _inject(
        M0678_VALUE,
        conditions=("Derivative(t**3 - 6*t**2 + 1, t).doit().subs(t, 5) = y",),
        answer="15",
        answer_map=(("y", "15"),),
        choices=("-15", "-4", "4", "15"),
        distractors=((0, "M0678"),),
    ),
    "M0678-unreadable": _inject(M0678_TIME, conditions=("s > 0",)),
}


@pytest.mark.parametrize("name", sorted(_RED))
def test_injected_misattribution_is_red(name: str) -> None:
    assert _RULE in _rules(_RED[name])


def test_m0676_names_missing_procedure_in_explanation() -> None:
    """해설이 절차를 보이지 않으면 '값이 아니다'가 아니라 '절차를 안 보인다'를 사유로 낸다.

    생성기 빌드가 멈출 때 사람이 고칠 곳(해설)을 가리키게 한다 — 사유가 바뀌면 RED.
    """
    stripped = _RED["M0676-explanation-stripped"]
    reasons = [v.reason for v in shortcut_violations(stripped) if v.rule == _RULE]
    assert any("해설이 M0676 절차" in r for r in reasons)


def test_new_clauses_stay_post_qualification() -> None:
    """같은 규칙 id 재사용 — 자격 측정 투표 집합(4회차 고정)을 바꾸지 않는다."""
    assert _RULE in POST_QUALIFICATION_RULE_IDS


def test_rolle_value_link_on_root_type_still_green() -> None:
    """근 값형 M0674(기존 절)는 개수형 분기로 새지 않는다 — f'(c) = 0의 근 -2/3 연결은 통과."""
    probe = ShortcutProbe(
        standard_code="[12미적Ⅰ-02-06]",
        question_text=(
            "함수 f(x) = x^3 - 2x^2 - 4x + 2에 대하여 곡선 y = f(x) 위의 두 점 A(-3, -31), B(0, 2) "
            "사이의 곡선 위에서 직선 AB와 평행한 접선을 갖는 점의 x좌표는?"
        ),
        answer="-5/3",
        explanation="f'(x) = 3x^2 - 4x - 4이다.",
        choices=("-3", "-5/3", "-2/3", "3"),
        conditions=(
            "Derivative(x**3 - 2*x**2 - 4*x + 2, x).doit().subs(x, c) = ((2) - (-31))/((0) - (-3))",
            "c > -3",
            "c < 0",
        ),
        answer_map=(("c", "-5/3"),),
        distractors=((2, "M0674"),),
    )
    assert _RULE not in _rules(probe)


@pytest.mark.parametrize("bank", ["problem_bank_p3_calculus1_diff_v0", "problem_bank_p3_fill_v0"])
def test_existing_banks_have_no_link_the_new_clauses_judge(bank: str) -> None:
    """소급 — 승인 은행에 새 절이 판정할 연결이 없다(있으면 소급 위반을 전수로 다시 재야 한다).

    스캔 0건은 실패로 본다(빈 파일을 읽고 통과하지 않게).
    """
    path = _ROOT / "data" / "corpus" / bank / "problems.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert records
    hits = []
    for record in records:
        probe = probe_from_record(record)
        for _, mid in probe.distractors:
            if mid in {"M0673", "M0676", "M0678"} or (
                mid == "M0674" and probe.answer_kind == "real_root_count"
            ):
                hits.append((record["problem_id"], mid))
    assert hits == []
