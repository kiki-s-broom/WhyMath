"""초등 어림 코퍼스 ↔ 한국 교과 관례 독립 대조(QUAL-11 회귀 동결).

배경: 과거 코퍼스는 발문이 "N을 X의 자리에서 올림하면"인데 정답은 "X의 자리까지 나타냄" 해석으로
계산돼 600문 중 537문이 교과 관례와 어긋났고, SymPy 검증은 생성기가 만든 조건식만 보므로 이를
잡지 못했다. 이 테스트는 **생성기와 무관한 독립 계산식**(`Decimal.quantize`)으로 코퍼스 전수를
재계산한다 — 생성기·코퍼스가 함께 틀려도 여기서 걸린다.

단언:
  ① 발문이 교과서 정식 표현("~하여 X의 자리까지 나타내면") 한 형태로만 구성된다(옛 "X의 자리에서"
     표현은 파싱 실패 = RED).
  ② 정답이 독립 계산식(관례 해석)과 600/600 일치한다(불일치 0).
  ③ 답이 입력값과 같은 문항이 0건이다.
  ④ 생성기 풀 전수도 같은 대조를 통과한다(코퍼스 재생성 시 결함 재유입 차단).
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from whymath_backend.harness.elementary_rounding_batch import CORPUS_DIR_NAME
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.elementary_rounding_skeleton_generator import (
    RoundingSkeletonGenerator,
)

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus" / CORPUS_DIR_NAME / "problems.jsonl"

# 교과서 정식 표현 — 전체 일치(옛 "X의 자리에서" 발문은 여기서 걸러진다).
_QUESTION = re.compile(
    r"^(?P<value>\d+)(?:을|를) (?P<op>올림|버림|반올림)하여 "
    r"(?P<place>십|백|천)의 자리까지 나타내면 얼마인지 구하시오\.$"
)
# "X의 자리까지" → 남기는 자리의 지수(십=10^1, 백=10^2, 천=10^3).
_EXPONENT = {"십": 1, "백": 2, "천": 3}
_ROUNDING = {"올림": ROUND_CEILING, "버림": ROUND_FLOOR, "반올림": ROUND_HALF_UP}


def _convention_answer(question_text: str) -> tuple[int, int]:
    """발문만 읽어 관례 정답을 독립 계산한다 — (값, 정답). 파싱 실패는 AssertionError."""
    match = _QUESTION.match(question_text)
    assert match, f"교과서 정식 표현이 아닌 발문: {question_text!r}"
    value = Decimal(match["value"])
    unit = Decimal(1).scaleb(_EXPONENT[match["place"]])  # 10 / 100 / 1000
    # value/unit을 정수로 어림한 뒤 다시 unit을 곱한다 — 생성기의 divmod 공식과 무관한 경로.
    scaled = (value / unit).quantize(Decimal(1), rounding=_ROUNDING[match["op"]])
    return int(value), int(scaled * unit)


def _corpus_records() -> list[dict]:
    assert _CORPUS.exists(), f"코퍼스 부재(공허 통과 금지): {_CORPUS}"
    records = [json.loads(line) for line in _CORPUS.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 600  # 스캔 0건·부분 스캔은 실패.
    return records


class TestCorpusMatchesKoreanConvention:
    def test_every_answer_matches_independent_convention_calculation(self) -> None:
        mismatches = []
        for record in _corpus_records():
            _value, expected = _convention_answer(record["question_text"])
            if str(expected) != record["answer"]:
                mismatches.append((record["question_text"], record["answer"], expected))
        assert not mismatches, f"관례 불일치 {len(mismatches)}건 예: {mismatches[:3]}"

    def test_no_answer_equals_input_value(self) -> None:
        degenerate = []
        for record in _corpus_records():
            value, _expected = _convention_answer(record["question_text"])
            if str(value) == record["answer"]:
                degenerate.append(record["question_text"])
        assert not degenerate, f"답=입력값 {len(degenerate)}건 예: {degenerate[:3]}"

    def test_explanation_states_the_matching_answer(self) -> None:
        for record in _corpus_records():
            assert f"구하는 값은 {record['answer']} 이다." in record["answer_explanation"]
            assert "의 자리에서 어림" not in record["answer_explanation"]  # 옛 해설 문구.


class TestGeneratorPoolMatchesConvention:
    @pytest.mark.parametrize("kind", ["ceil", "floor", "round"])
    def test_full_pool_matches_and_has_no_degenerate_input(self, kind: str) -> None:
        generator = RoundingSkeletonGenerator(kind=kind)  # type: ignore[arg-type]
        seen = 0
        while (candidate := generator.generate(_spec())) is not None:
            value, expected = _convention_answer(candidate.problem.question_text)
            assert candidate.problem.answer == str(expected), candidate.problem.question_text
            assert candidate.problem.answer != str(value), candidate.problem.question_text
            seen += 1
        assert seen == 300  # 풀 전수를 실제로 순회했다(0건 공허 통과 금지).


def _spec() -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=frozenset({"[6수01-03]"}),
        target_misconception_ids=frozenset(),
        difficulty_overall=1.5,
        answer_format=None,
    )
