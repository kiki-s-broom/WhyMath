"""검산식 우회(동어반복) 판정 — `l3/equivalent/verify_bypass` (EOS-207).

판정 분기마다 반례와 대조군을 둔다(절마다 '그 절이 없으면 무엇이 통과하는가'의 입력):
  ① 재진술 — 정답 상수만 쓰는 등식(부호 이동·분수·무리수·항등 연산 끼워 넣기 포함)
  ② 재계산 대조군 — 정답에 없는 수로 정답을 다시 내는 등식(강·약 둘 다 RECOMPUTE)
  ③ 무조건 참 — 정답 변수 미포함·잔차 항등 0
  ④ 판정 불가 — 파싱 불가·부등식만·정답 밖 자유 기호·연립·answer_map 부재·정답 표기 불가
  ⑤ 결합 규칙 — 재계산 우선·판정 불가 전파·부등식은 결합에서 제외
  ⑥ 실데이터 — EOS-197 A6 30 CU에서 재진술 17건(검수 메모 실측과 같은 수)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.l3.equivalent.verify_bypass import (
    BypassKind,
    classify_condition,
    classify_verify_bypass,
)

_REPO = Path(__file__).resolve().parents[4]


def _verify(conditions: object, answer_map: object) -> dict[str, object]:
    return {"conditions": conditions, "answer_map": answer_map, "answer_selection": "unique"}


# ── ① 재진술 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("condition", "var", "answer"),
    [
        ("n = 3", "n", "3"),
        ("v - 24 = 0", "v", "24"),
        ("y + 3 = 0", "y", "-3"),  # 부호 이동 — 정답 -3의 크기 3만 쓴다
        ("b == -31", "b", "-31"),  # 파이썬식 등호
        ("y + 1/2 = 0", "y", "-1/2"),  # 분수 표기는 리터럴 하나(-1/2는 AST에서 (-1)/2)
        ("x - sqrt(2) = 0", "x", "sqrt(2)"),  # 무리수 정답 — 정답 표기의 리터럴과 같다
        ("n = 1*3", "n", "3"),  # 항등 연산(1*)으로 우회하지 못한다
        ("n = 3 + 0", "n", "3"),  # 항등 연산(+0)으로 우회하지 못한다
        ("y = 1", "y", "1"),  # 정답이 1 — 리터럴 다중집합이 둘 다 비어 같다
    ],
)
def test_restatement_is_bypass(condition: str, var: str, answer: str) -> None:
    verdict = classify_verify_bypass(_verify(condition, {var: answer}))
    assert verdict.kind is BypassKind.RESTATEMENT
    assert verdict.bypassed is True


# ── ② 재계산 대조군 ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("condition", "var", "answer"),
    [
        ("v = 4*3 + 7", "v", "19"),
        ("answer == (2**3 - 5*2 + 2) - 2*(3*2**2 - 5)", "answer", "-14"),
        ("M**2 - M - 182 = 0", "M", "14"),  # 역설계 이차식 — 약하지만 재진술은 아니다(한계)
        ("2 = -4 + b", "b", "6"),  # 미리 구한 기울기를 쓴 역산 — 약한 재계산(한계)
        ("y = -2*0 + 1", "y", "1"),  # 정답 1이지만 2를 쓴다
        ("2*y = 3", "y", "3/2"),  # 분수 정답을 계수로 다시 낸다
        ("n**2 = 9", "n", "3"),
    ],
)
def test_recompute_is_not_bypass(condition: str, var: str, answer: str) -> None:
    verdict = classify_verify_bypass(_verify(condition, {var: answer}))
    assert verdict.kind is BypassKind.RECOMPUTE
    assert verdict.bypassed is False


def test_same_literal_twice_is_recompute_not_restatement() -> None:
    """다중집합이지 집합이 아니다 — `n + 3 = 3 + 3`(정답 3)는 3을 세 번 쓴다(재진술이 아니다)."""
    assert classify_condition("n + 3 = 3 + 3", {"n": "3"}).kind is BypassKind.RECOMPUTE


# ── ③ 무조건 참 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "condition",
    [
        "n = n",
        "2 = 2",
        "n - n = 0",
        # 잔차가 정답 변수를 *쓰면서* 항등 0인 꼴 — 파서가 전개하지 않으므로 '정답 변수 미포함'
        # 절이 아니라 항등 0 절만이 잡는다(뮤테이션 M4 생존으로 드러난 미접촉 절의 반례).
        "(n + 1)**2 = n**2 + 2*n + 1",
    ],
)
def test_identity_is_bypass(condition: str) -> None:
    verdict = classify_verify_bypass(_verify(condition, {"n": "3"}))
    assert verdict.kind is BypassKind.IDENTITY
    assert verdict.bypassed is True


# ── ④ 판정 불가 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("verify", "needle"),
    [
        (None, "verify 블록 없음"),
        ({"conditions": "", "answer_map": {"n": "3"}}, "검산 조건 없음"),
        ({"conditions": 3, "answer_map": {"n": "3"}}, "검산 조건 없음"),
        ({"conditions": "n = 3", "answer_map": {}}, "answer_map"),
        (_verify(["0 < k", "k < 8"], {"k": "7"}), "등식 없음"),
        (_verify("y = -3*x + 10", {"y": "10"}), "판정 불가 등식"),  # 정답 밖 자유 기호 x
        (_verify("x + y = 5", {"x": "2", "y": "3"}), "판정 불가 등식"),  # 연립
        (_verify("n = = 3", {"n": "3"}), "등식 없음"),  # 파싱 불가(등식으로도 못 읽음)
        (_verify("n = 3", {"n": "3,,"}), "판정 불가 등식"),  # 정답 표기 불가
    ],
)
def test_undecidable_is_three_state_none(verify: object, needle: str) -> None:
    verdict = classify_verify_bypass(verify)  # type: ignore[arg-type]
    assert verdict.kind is BypassKind.UNDECIDABLE
    assert verdict.bypassed is None  # 모른다 ≠ 아니다
    assert needle in verdict.reason


def test_extra_free_symbol_reason_names_the_symbol() -> None:
    verdict = classify_condition("y = -3*x + 10", {"y": "10"})
    assert verdict.kind is BypassKind.UNDECIDABLE
    assert "'x'" in verdict.reason


# ── ⑤ 결합 규칙 ──────────────────────────────────────────────────────────
def test_recompute_wins_over_restatement() -> None:
    verdict = classify_verify_bypass(_verify(["n = 3", "n = 1 + 2"], {"n": "3"}))
    assert verdict.kind is BypassKind.RECOMPUTE


def test_undecidable_equation_blocks_bypass_verdict() -> None:
    verdict = classify_verify_bypass(_verify(["n = 3", "n = k"], {"n": "3"}))
    assert verdict.kind is BypassKind.UNDECIDABLE


def test_domain_inequality_does_not_rescue_a_restatement() -> None:
    """도메인 부등식은 값을 정하지 않는다 — `n = 3` + `n > 0`은 여전히 우회다."""
    verdict = classify_verify_bypass(_verify(["n = 3", "n > 0"], {"n": "3"}))
    assert verdict.kind is BypassKind.RESTATEMENT
    assert [c.is_equation for c in verdict.conditions] == [True, False]


def test_identity_only_set_reports_identity() -> None:
    verdict = classify_verify_bypass(_verify(["n = n", "2 = 2"], {"n": "3"}))
    assert verdict.kind is BypassKind.IDENTITY


def test_to_json_carries_per_condition_reasons() -> None:
    payload = classify_verify_bypass(_verify("n = 3", {"n": "3"})).to_json()
    assert payload["kind"] == "restatement"
    assert payload["bypassed"] is True
    assert payload["conditions"][0]["condition"] == "n = 3"  # type: ignore[index]


# ── ⑥ 실데이터 ───────────────────────────────────────────────────────────
def test_eos197_round_has_seventeen_restatements() -> None:
    """EOS-197 A6 30 CU — 검수 메모가 실측한 '동어반복 17건'과 기계 판정이 같다(EOS-205 근거)."""
    kinds: dict[str, int] = {}
    for seat in ("local", "openrouter"):
        path = _REPO / "data" / "runs" / f"eos197-a6-{seat}" / "cu.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                verdict = classify_verify_bypass(json.loads(line)["verify"])
                kinds[verdict.kind.value] = kinds.get(verdict.kind.value, 0) + 1
    assert kinds == {"restatement": 17, "recompute": 13}
