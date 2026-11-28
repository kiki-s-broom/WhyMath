"""S31R(반복 회차 · GOLD-42 · F-07) 특성화 — 튜터 문장의 정답 노출을 옛 함수들이 무엇으로 판정하는가.

옛 자산 경계는 `golden/HARVEST.md` 「반복 슬롯 T3R 경계 (S31R)」에 있다. 이 테스트는 옛 함수를
**옛 자리에서** 불러(골든 코드는 import하지 않는다 — `golden/LEGACY_MANIFEST.txt`) 입력 10개의 출력을 고정한다.
동작이 맞는지는 묻지 않고, 바뀌지 않는지만 본다. S32R이 복사한 뒤에도 같은 출력이 나와야 한다.

입력 출처 — S31R 보고(`golden/reports_phase1r/S31R/보고.md`)의 유출 출처 표:
- ⓑ 학생이 낸 맞는 값을 되짚음 · ⓒ M1 규칙의 오탐(학생의 부호 반대 오답을 되짚음): Kiki PC 실제 LLM 실행
  기록에서 뽑은 **튜터 문장**(시뮬레이터 학생 문장·시드 문장은 넣지 않는다).
- ⓐ 튜터가 새로 말함: 실제 기록에서 **0건**이었다(1,285세션 · 유출 21세션 29턴 전부 ⓑ·ⓒ). 그래서 ⓐ 두 줄은
  **합성** 문장이다(`source="합성"` · `golden/DECISIONS_AUTO.md` 2026-11-28 S31R 줄).
- 대조군 1줄: 숫자가 없는 되묻기(합성).
"""

from __future__ import annotations

from typing import Any

import pytest
from golden.sim.metrics import LeakageVerdict, detect_answer_leakage

# 고정 입력 10개 — kind: a_synth(ⓐ 합성) · b_real(ⓑ 실제) · c_real(ⓒ 실제) · control(대조군)
# 기대값: m1 = 지금 M1 규칙(비교용) · scan = 옛 값 축 `scan_value_exposure` (결과, 잡은 조각) · sub = 옛
# `_detect_answer_leak`(부분 문자열)
_ROWS: list[dict[str, Any]] = [
    {
        "id": "c1",
        "kind": "c_real",
        "source": "야간 2026-11-24 · P2 · LF-07 · 턴 1",
        "answer": "11",
        "tutor": "답이 -11이라고 생각했군요. 그 값을 얻기 위해 문제의 함수에서 x 자리에 무엇을 넣어 어떤 식을 세웠는지, 그 식을 그대로 보여 줄래요?",
        "m1": "leaked",
        "scan": ("clean", None),
        "sub": True,
    },
    {
        "id": "c2",
        "kind": "c_real",
        "source": "S28R f0 · P2 · LF-15 · 턴 1",
        "answer": "2/3",
        "tutor": "문제의 식에서 x에 곱해진 수를 -2/3라고 본 거군요. 그 수를 어떻게 찾았는지 떠올리면서, 문제의 식을 y = (수)x + (수) 꼴로 놓았을 때 x 바로 앞에 쓰인 수는 무엇인지 다시 확인해 볼래요?",
        "m1": "leaked",
        "scan": ("clean", None),
        "sub": True,
    },
    {
        "id": "c3",
        "kind": "c_real",
        "source": "S28R f0 · P3 · LF-16 · 턴 3",
        "answer": "15",
        "tutor": "세 번 모두 -15라고 말했군요. 그 -15 앞에 붙은 음수 부호를 그대로 다시 보면서, 문제에서 x가 늘어날 때 y의 증가량이 얼마인지 지금 바로 말해 볼래요?",
        "m1": "leaked",
        "scan": ("clean", None),
        "sub": True,
    },
    {
        "id": "b1",
        "kind": "b_real",
        "source": "S28R f0 · P6 · LF-08 · 턴 2",
        "answer": "16",
        "tutor": "f(5)가 16이라고 했군요. 그 값을 어떻게 얻었는지, 문제의 식에서 어느 자리에 무엇을 넣어 계산했는지 말해 볼래요?",
        "m1": "leaked",
        "scan": ("clean", None),
        "sub": True,
    },
    {
        "id": "b2",
        "kind": "b_real",
        "source": "야간 2026-11-26 · P2 · LF-16 · 턴 3",
        "answer": "15",
        "tutor": "문제의 식에 3을 넣은 값에 15를 더한 셈인 ‘5*(3)+15’라고 쓴 부분이 보이는데, 거기서 그 더하기 15는 어디서 나온 것인지 한번 짚어 보면서, x가 3만큼 증가할 때 y의 증가량이 얼마인지 직접 구해 말해 볼래요?",
        "m1": "leaked",
        "scan": ("clean", None),
        "sub": True,
    },
    {
        "id": "b3",
        "kind": "b_real",
        "source": "S28R f0 · P2 · LF-16 · 턴 2",
        "answer": "15",
        "tutor": "x가 3만큼 늘 때 5×3을 계산해서 15만큼 늘어난다고 보았는데, 처음에는 y의 증가량을 -6이라고 했군요. 이 두 값이 서로 다른데, 어느 쪽이 y의 증가량이라고 생각하는지 말해 줄래요?",
        "m1": "leaked",
        "scan": ("exposed", "5*3"),
        "sub": True,
    },
    {
        "id": "b4",
        "kind": "b_real",
        "source": "S33 out · P2 · LF-09 · 턴 2",
        "answer": "-4",
        "tutor": "이번에는 -4라고 생각했군요. 그 생각이 나오게 된 과정을, 문제의 식에서 어느 부분에 무엇을 넣어 어떻게 계산했는지 말해 볼래요?",
        "m1": "leaked",
        "scan": ("clean", None),
        "sub": True,
    },
    {
        "id": "a1",
        "kind": "a_synth",
        "source": "합성",
        "answer": "16",
        "tutor": "x 자리에 5를 넣으면 3×5+1 = 16이니까 답은 16이에요.",
        "m1": "leaked",
        "scan": ("exposed", "3*5+1"),
        "sub": True,
    },
    {
        "id": "a2",
        "kind": "a_synth",
        "source": "합성",
        "answer": "4",
        "tutor": "6*2-8을 계산하면 무엇이 나오는지 말해 볼래요?",
        "m1": "undecidable",
        "scan": ("exposed", "6*2-8"),
        "sub": False,
    },
    {
        "id": "k1",
        "kind": "control",
        "source": "합성",
        "answer": "11",
        "tutor": "그 값을 얻기 위해 x 자리에 무엇을 넣어 어떤 식을 세웠는지 말해 볼래요?",
        "m1": "clean",
        "scan": ("clean", None),
        "sub": False,
    },
]
_IDS = [r["id"] for r in _ROWS]


def test_table_shape() -> None:
    """입력 10개 · ⓐ·ⓑ 하나 이상씩(지시서 S31R 할 일 4) · ⓒ와 대조군도 하나 이상 — 공허한 통과 금지."""
    kinds = [r["kind"] for r in _ROWS]
    assert len(_ROWS) == 10
    assert len(set(_IDS)) == 10
    assert kinds.count("a_synth") >= 1
    assert kinds.count("b_real") >= 1
    assert kinds.count("c_real") >= 1
    assert kinds.count("control") >= 1
    # 실제 사례는 출처가 실행·페르소나·문항·턴으로 적혀 있다
    assert all("LF-" in r["source"] for r in _ROWS if r["kind"].endswith("_real"))


@pytest.mark.parametrize("row", _ROWS, ids=_IDS)
def test_legacy_value_axis_output_is_frozen(row: dict[str, Any]) -> None:
    """옛 값 축 `l3/verify_solution.py::scan_value_exposure` — 닫힌 식의 값만 본다(맨 숫자는 안 본다)."""
    from whymath_backend.l3.verify_solution import scan_value_exposure

    got = scan_value_exposure(row["tutor"], row["answer"])
    assert (got.outcome.value, got.fragment) == row["scan"]


@pytest.mark.parametrize("row", _ROWS, ids=_IDS)
def test_legacy_substring_output_is_frozen(row: dict[str, Any]) -> None:
    """옛 `l3/pedagogy/analogy_checker.py::_detect_answer_leak` — 정답 문자열이 본문에 있는가(부분 문자열)."""
    from whymath_backend.l3.pedagogy.analogy_checker import _detect_answer_leak

    assert _detect_answer_leak(row["tutor"], row["answer"]) is row["sub"]


@pytest.mark.parametrize("row", _ROWS, ids=_IDS)
def test_current_m1_rule_for_comparison(row: dict[str, Any]) -> None:
    """비교용 — 지금 M1 규칙(측정 도구 · 옛 자산 아님). 이 테스트는 M1 정의를 바꾸지 않는다(공유 계약)."""
    assert detect_answer_leakage(row["tutor"], row["answer"]) is LeakageVerdict(row["m1"])


def test_boundary_facts() -> None:
    """HARVEST 판정의 근거 — 세 가지 사실을 한곳에서 고정한다.

    ① 부분 문자열 함수는 ⓒ(부호 반대 오답의 되짚기)를 전부 유출로 본다 → 버림.
    ② 값 축은 ⓐ 합성 2줄을 모두 잡고(M1이 유보하는 1글자 정답 포함), ⓒ는 하나도 잡지 않는다.
    ③ 값 축도 ⓑ 중 학생 식을 되짚은 줄(b3)은 잡는다 — 그래서 S32R은 값 축만으로 막지 말고 "그 값이 이 턴까지
       학생 입력에 있었나"로 ⓑ를 먼저 걸러야 한다(지시서 S32R 할 일 2 "ⓑ는 막지 않는다").
    """
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for r in _ROWS:
        by_kind.setdefault(r["kind"], []).append(r)
    assert all(r["sub"] for r in by_kind["c_real"])
    assert all(r["scan"][0] == "exposed" for r in by_kind["a_synth"])
    assert all(r["scan"][0] == "clean" for r in by_kind["c_real"])
    assert [r["id"] for r in by_kind["b_real"] if r["scan"][0] == "exposed"] == ["b3"]
