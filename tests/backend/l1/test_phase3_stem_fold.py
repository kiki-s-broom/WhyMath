"""문면 근사 중복 접기(P3-05) — 순수 함수 계약.

각 테스트는 "그 규칙이 없으면 통과해 버리는 입력"을 하나씩 갖는다(픽스처가 절을 실제로 밟는다).
"""

from __future__ import annotations

import pytest

from whymath_backend.l1.standards.phase3_stem_fold import (
    NUMBER_PLACEHOLDER,
    DistinctCount,
    distinct_count,
    fold_stem,
)


class TestFoldStem:
    def test_numbers_are_folded_so_a_numbers_only_variant_is_the_same_problem(self) -> None:
        a = "함수 f(x) = x^3 - 3x 의 x = 2 에서의 미분계수를 구하시오."
        b = "함수 f(x) = x^5 - 7x 의 x = 9 에서의 미분계수를 구하시오."
        assert fold_stem(a) == fold_stem(b)

    def test_decimals_are_folded_as_one_number_not_two(self) -> None:
        """소수 `3.5` 를 정수 둘(`#.#`)로 접으면 `3.5` 와 `3` 이 다른 문제가 돼 버린다."""
        assert fold_stem("속도가 3.5 일 때") == fold_stem("속도가 3 일 때") == "속도가 # 일 때"

    def test_whitespace_differences_do_not_make_a_different_problem(self) -> None:
        assert fold_stem("f(x)  =  x^2\n의 값") == fold_stem("f(x) = x^2 의 값")

    def test_a_different_structure_is_not_merged(self) -> None:
        """대조군 — 숫자 접기가 과해서 구조가 다른 문제까지 합치면 안 된다."""
        a = "함수 f(x) = x^3 의 극값의 개수를 구하시오."
        b = "함수 f(x) = x^3 의 변곡점의 개수를 구하시오."
        assert fold_stem(a) != fold_stem(b)

    def test_variable_names_are_not_folded_yet(self) -> None:
        """2단(변수 이름 접기)은 보류다 — 코퍼스에 그런 변형이 없다. 이 테스트가 그 사실을 고정한다.

        2단을 도입하면 이 테스트가 먼저 깨져서 의도적 변경임을 드러낸다.
        """
        assert fold_stem("f(x) = x^2 의 값") != fold_stem("g(t) = t^2 의 값")

    @pytest.mark.parametrize("unknown", [None, "", "   ", "\n\t"])
    def test_unknown_or_blank_stem_has_no_fold(self, unknown: str | None) -> None:
        assert fold_stem(unknown) is None

    def test_placeholder_constant_is_what_the_fold_uses(self) -> None:
        assert fold_stem("값 7") == f"값 {NUMBER_PLACEHOLDER}"


class TestSameDefinitionAsTheGenerator:
    """문면 접기(숫자를 #로 접은 문면)의 정의가 두 곳에 따로 있다 — 생성기 `skeleton_of` 와 계측기 `fold_stem`.

    생성기가 "서로 다르다"고 만든 문항을 계측기가 "같다"고 세면, 5단계 신규 생성에서 칸이 안 채워진다.
    구현 통합은 후속으로 분리했으므로(이 PR은 생성기를 건드리지 않는다) 두 구현이 어긋나지 않는다는 것을
    이 테스트가 지킨다. 어긋나면 어느 쪽이 정본인지 먼저 정하라는 신호다.
    """

    _SAMPLES = (
        "함수 f(x) = x^3 - 3x 의 극값의 개수를 구하시오.",
        "속도 3.5 와 가속도 12 일 때\n거리를  구하시오.",
        "f'(2) = 10 일 때 a 의 값은?",
        "숫자가 없는 문면",
    )

    @pytest.mark.parametrize("text", _SAMPLES)
    def test_agrees_on_samples_that_exercise_integers_decimals_and_whitespace(
        self, text: str
    ) -> None:
        from whymath_backend.l3.equivalent.p3_diff_skeleton_base import skeleton_of

        assert fold_stem(text) == skeleton_of(text)

    def test_agrees_on_every_stem_of_the_real_corpus_and_the_scan_is_not_vacuous(self) -> None:
        import glob
        import json
        from pathlib import Path

        from whymath_backend.l3.equivalent.p3_diff_skeleton_base import skeleton_of

        root = Path(__file__).resolve().parents[3]
        compared = 0
        differing: list[str] = []
        for path in sorted(glob.glob(str(root / "data/corpus/problem_bank_*/problems.jsonl"))):
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                stem = json.loads(line).get("question_text")
                if not isinstance(stem, str) or not stem.strip():
                    continue
                compared += 1
                if fold_stem(stem) != skeleton_of(stem):
                    differing.append(stem[:60])
        # 스캔 0건은 실패다 — 코퍼스를 못 찾아 아무것도 비교하지 않고 통과하는 길을 막는다.
        assert (
            compared > 10_000
        ), f"비교한 문면이 너무 적다({compared}건) — 코퍼스를 못 읽었을 수 있다"
        assert differing == [], differing[:3]


class TestDistinctCount:
    def test_numbers_only_variants_count_once(self) -> None:
        stems = [f"f(x) = x^2 에서 f'({n}) 의 값을 구하시오." for n in range(1, 6)]
        assert distinct_count(stems) == DistinctCount(distinct=1, unfolded=0, total=5)

    def test_structurally_different_problems_each_count(self) -> None:
        stems = [
            "극값의 개수를 구하시오.",
            "변곡점의 개수를 구하시오.",
            "접선의 기울기를 구하시오.",
        ]
        assert distinct_count(stems).distinct == 3

    def test_unknown_stems_are_never_merged_with_each_other(self) -> None:
        """모르는 것끼리 '같다'고 하면 측정 못 한 것이 중복 제거로 위장된다 — 각각 1건이다."""
        result = distinct_count([None, None, "", "   "])
        assert result == DistinctCount(distinct=4, unfolded=4, total=4)

    def test_unknown_and_known_are_counted_separately(self) -> None:
        result = distinct_count(["극값을 구하시오 1", "극값을 구하시오 2", None])
        assert result == DistinctCount(distinct=2, unfolded=1, total=3)

    def test_empty_input_is_zero_not_an_error(self) -> None:
        assert distinct_count([]) == DistinctCount(distinct=0, unfolded=0, total=0)

    def test_works_on_a_generator_once(self) -> None:
        """호출부가 제너레이터를 넘긴다 — 한 번만 소비해도 세 값이 일관돼야 한다."""
        result = distinct_count(s for s in ["a 1", "a 2", None])
        assert (result.distinct, result.unfolded, result.total) == (2, 1, 3)
