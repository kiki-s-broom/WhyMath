"""발문 의미 어휘(경계 방향·한정)가 걸린 문항의 독립 계산 동결(QUAL-12).

대상 코퍼스(어휘가 실제로 있는 곳 — `test_stem_semantic_hook_coverage.py` 레지스트리와 쌍):
  - problem_bank_probability_finite_v0 : "정확히 k번"(이항) · "합이 k 이상"(주사위 전수 열거)
  - problem_bank_p3_calculus1_diff_v0  : "n은 2 이상의 자연수"(n 탐색) · "항상 … 최솟값"(구간 최솟값)

생성기를 호출하지 않는다 — 발문 문장만 파싱해 정답을 다시 계산하고 저장 answer와 대조한다.
발문이 아는 형태가 아니면(파싱 실패) 통과가 아니라 RED다. 어휘가 걸린 행이 0건이어도 RED다.
(어림 코퍼스는 `test_elementary_rounding_corpus_convention.py`가 따로 동결한다.)
"""

from __future__ import annotations

import json
import re
from fractions import Fraction
from itertools import product
from math import comb
from pathlib import Path

import pytest
import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS_ROOT = _ROOT / "data" / "corpus"
_PF = "problem_bank_probability_finite_v0"
_P3 = "problem_bank_p3_calculus1_diff_v0"

# 어휘 계열 선택자 — 거버넌스 테스트의 경계방향·한정과 같은 어휘(독립 정의).
_HOOK = re.compile(r"이상|이하|초과|미만|적어도|많아야|정확히|반드시|항상")

_COIN = re.compile(
    r"^한 개의 동전을 (?P<n>\d+)번 던진다\. 매번 앞면과 뒷면이 나올 가능성이 같을 때, "
    r"앞면이 정확히 (?P<k>\d+)번 나올 확률을 기약분수로 나타내시오\.$"
)
_DICE = re.compile(
    r"^서로 구별되는 두 개의 주사위를 동시에 던진다\. 나온 두 눈의 수의 합이 (?P<k>\d+) 이상이 되는 "
    r"경우의 수를 구하시오\. \(두 주사위는 서로 구별하며, 눈의 순서가 다르면 다른 경우로 센다\.\)$"
)
_HEAD = r"^함수 f\(x\) = x\^n \(n은 2 이상의 자연수\)"
_P3_N = re.compile(
    _HEAD + r"에 대하여 f'\((?P<a>\d+)\)의 값이 (?P<v>\d+)일 때, n의 값을 구하시오\.$"
)
_P3_K = re.compile(
    _HEAD + r"의 도함수가 f'\(x\) = kx\^(?P<m>\d+) \(k는 상수\)일 때, k의 값을 구하시오\.$"
)
_P3_NEXT = re.compile(
    _HEAD
    + r"에 대하여 f'\((?P<a>\d+)\)의 값이 (?P<v>\d+)일 때, f'\((?P<b>\d+)\)의 값을 구하시오\.$"
)
_P3_MIN = re.compile(
    r"^수직선 위를 움직이는 두 점 P, Q의 시각 t \(t ≥ 0\)에서의 위치가 각각 "
    r"p\(t\) = (?P<p>[^,]+), q\(t\) = (?P<q>.+)이다\. "
    r"t ≥ 0에서 점 P는 항상 점 Q보다 오른쪽에 있음을 보이려 한다\. "
    r"t ≥ 0에서 p\(t\) - q\(t\)의 최솟값을 구하시오\.$"
)
_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)


def _find_n(a: int, v: int) -> int:
    """x^n의 f'(a)=n·a^(n-1)=v를 만족하는 n(≥2)을 탐색 — 유일하지 않으면 AssertionError."""
    hits = [n for n in range(2, 40) if n * a ** (n - 1) == v]
    assert len(hits) == 1, f"n이 유일하지 않음: a={a} v={v} hits={hits}"
    return hits[0]


def _min_difference(p_text: str, q_text: str) -> sympy.Expr:
    """t ≥ 0에서 p−q의 최솟값 — 임계점과 경계 t=0만 비교(삼차 이상 양의 선행계수 가정은 검증)."""
    t = sympy.Symbol("t", real=True)
    diff = sympy.expand(
        parse_expr(p_text, {"t": t}, transformations=_TRANSFORMS)
        - parse_expr(q_text, {"t": t}, transformations=_TRANSFORMS)
    )
    assert sympy.Poly(diff, t).LC() > 0, f"선행계수가 양수가 아니면 최솟값이 없을 수 있다: {diff}"
    candidates = [sympy.Integer(0)] + [
        r for r in sympy.solve(sympy.diff(diff, t), t) if r.is_real and r >= 0
    ]
    return min(diff.subs(t, c) for c in candidates)


def independent_answer(stem: str) -> str:
    """발문만 읽어 정답 문자열을 독립 계산한다. 아는 형태가 아니면 AssertionError."""
    if m := _COIN.match(stem):
        n, k = int(m["n"]), int(m["k"])
        return str(Fraction(comb(n, k), 2**n))
    if m := _DICE.match(stem):
        return str(sum(1 for a, b in product(range(1, 7), repeat=2) if a + b >= int(m["k"])))
    if m := _P3_N.match(stem):
        return str(_find_n(int(m["a"]), int(m["v"])))
    if m := _P3_K.match(stem):
        return str(int(m["m"]) + 1)  # f'(x)=n·x^(n-1)=k·x^m → n=m+1, k=n.
    if m := _P3_NEXT.match(stem):
        n = _find_n(int(m["a"]), int(m["v"]))
        return str(n * int(m["b"]) ** (n - 1))
    if m := _P3_MIN.match(stem):
        return str(_min_difference(m["p"], m["q"]))
    raise AssertionError(f"알 수 없는 발문 형태(파싱 실패 = RED): {stem!r}")


def hook_rows(corpus: str) -> list[dict]:
    path = _CORPUS_ROOT / corpus / "problems.jsonl"
    assert path.exists(), f"코퍼스 부재(공허 통과 금지): {path}"
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    selected = [r for r in rows if _HOOK.search(r["question_text"])]
    assert selected, f"{corpus}: 어휘가 걸린 행 0건 — 등록이 낡았거나 스캔 실패"
    return selected


def mismatches(rows: list[dict]) -> list[tuple[str, str, str]]:
    return [
        (r["question_text"], r["answer"], expected)
        for r in rows
        if (expected := independent_answer(r["question_text"])) != r["answer"]
    ]


@pytest.mark.parametrize("corpus", [_PF, _P3])
def test_hook_rows_match_independent_calculation(corpus: str) -> None:
    rows = hook_rows(corpus)
    bad = mismatches(rows)
    assert not bad, f"{corpus}: 불일치 {len(bad)}/{len(rows)} 예: {bad[:3]}"


def test_expected_stem_families_are_all_exercised() -> None:
    """네 형태가 모두 실제 행에서 한 번 이상 쓰였다 — 형태 하나가 죽어도 통과하는 위장 차단."""
    seen = {"coin": 0, "dice": 0, "n": 0, "k": 0, "next": 0, "min": 0}
    for corpus in (_PF, _P3):
        for row in hook_rows(corpus):
            s = row["question_text"]
            for name, pattern in (
                ("coin", _COIN),
                ("dice", _DICE),
                ("n", _P3_N),
                ("k", _P3_K),
                ("next", _P3_NEXT),
                ("min", _P3_MIN),
            ):
                if pattern.match(s):
                    seen[name] += 1
    assert all(seen.values()), f"쓰이지 않은 형태가 있다: {seen}"


class TestCheckerDiscriminates:
    """검사기 변별력 — 결함을 주입한 사본에서 RED가 나와야 한다(주입이 적용됐음을 먼저 단언)."""

    def _rows(self) -> list[dict]:
        return hook_rows(_PF) + hook_rows(_P3)

    def test_corrupting_every_answer_is_detected(self) -> None:
        rows = [{**r, "answer": r["answer"] + "0"} for r in self._rows()]
        assert all(m["answer"] != o["answer"] for m, o in zip(rows, self._rows(), strict=True))
        assert len(mismatches(rows)) == len(rows)

    def test_flipping_geq_to_leq_in_dice_stem_is_detected(self) -> None:
        dice = [r for r in hook_rows(_PF) if _DICE.match(r["question_text"])]
        flipped = [{**r, "question_text": r["question_text"].replace("이상", "이하")} for r in dice]
        assert all(
            f["question_text"] != d["question_text"] for f, d in zip(flipped, dice, strict=True)
        )
        with pytest.raises(AssertionError, match="파싱 실패"):
            mismatches(flipped)  # 경계 방향어가 바뀌면 아는 형태가 아니다 = RED.

    def test_wrong_boundary_interpretation_is_detected(self) -> None:
        # "k 이상"을 "k 초과"로 읽은 값을 정답으로 저장한 행 — 경계 포함 여부 불일치(QUAL-11형).
        dice = [r for r in hook_rows(_PF) if _DICE.match(r["question_text"])]
        wrong = []
        for r in dice:
            k = int(_DICE.match(r["question_text"])["k"])
            exclusive = sum(1 for a, b in product(range(1, 7), repeat=2) if a + b > k)
            wrong.append({**r, "answer": str(exclusive)})
        assert all(w["answer"] != d["answer"] for w, d in zip(wrong, dice, strict=True))
        assert len(mismatches(wrong)) == len(dice)

    def test_min_vs_boundary_value_confusion_is_detected(self) -> None:
        # 최솟값 대신 t=0 값(경계)을 저장한 행.
        rows = [r for r in hook_rows(_P3) if _P3_MIN.match(r["question_text"])]
        wrong = []
        for r in rows:
            m = _P3_MIN.match(r["question_text"])
            t = sympy.Symbol("t")
            at_zero = (
                parse_expr(m["p"], {"t": t}, transformations=_TRANSFORMS)
                - parse_expr(m["q"], {"t": t}, transformations=_TRANSFORMS)
            ).subs(t, 0)
            wrong.append({**r, "answer": str(at_zero)})
        assert any(w["answer"] != o["answer"] for w, o in zip(wrong, rows, strict=True))
        assert mismatches(wrong), "경계값을 최솟값으로 오인한 행이 하나도 안 잡혔다"

    def test_unknown_stem_is_red_not_pass(self) -> None:
        with pytest.raises(AssertionError, match="파싱 실패"):
            independent_answer("동전을 던진다.")

    def test_empty_selection_is_red(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        corpus = tmp_path / "problem_bank_empty_v0"
        corpus.mkdir()
        (corpus / "problems.jsonl").write_text(
            json.dumps({"question_text": "어휘 없는 발문", "answer": "1"}) + "\n", encoding="utf-8"
        )
        monkeypatch.setattr(f"{__name__}._CORPUS_ROOT", tmp_path)
        with pytest.raises(AssertionError, match="0건"):
            hook_rows("problem_bank_empty_v0")
