"""극값 단답형 ↔ 객관식 생성기의 **발문 공간 서로소** 동결 (QUAL-08).

배경: 두 생성기(`CalculusExtremumValueSkeletonGenerator` 단답형 ·
`CalculusExtremumMCSkeletonGenerator` 객관식)는 같은 삼차함수 뼈대 공간을 공유한다 —
`(m, n, kind)` 기준 140쌍이 겹친다(전수 실측). 초판은 발문 템플릿의 첫 항목까지 글자 그대로
같아서 **같은 발문이 두 형식으로 생성됐고**(공간 22건 · 코퍼스 4건 실재) 그 4건은 해시 접미마저
같았다(`wm-calc-extv-bd21cd8484d2` ↔ `wm-calc-extmc-bd21cd8484d2`).

여기서 동결하는 계약은 **발문 축**이다 — 객관식 템플릿은 단답형 템플릿과 한 건도 공유하지
않으며 전부 *선택 지시*다. 뼈대 공간 자체의 분할(같은 뼈대를 정확히 한 형식에만 배정 —
`skeleton_generator._MC_PARTITION_MOD` 선례)은 코퍼스 재생성을 동반하므로 이 테스트의 범위가
아니다(승계 태스크). 그 사실도 아래 테스트가 명시적으로 기록한다 — "안 나왔다"와 "안 봤다"는
다르다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.equivalent import calculus_skeleton_generator as calc
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec

_SPEC = EquivalenceSpec(
    achievement_standard_codes=frozenset({"[12미적Ⅰ-02-07]"}),
    target_misconception_ids=frozenset(),
    difficulty_overall=3.4,
    answer_format=None,
)

_MC_CODES = {
    "max_min": ("MISC-TEST-MAXMIN", "OP-TEST-MAXMIN"),
    "value_vs_point": ("MISC-TEST-VVP", "OP-TEST-VVP"),
}


def _drain_questions(generator: object) -> set[str]:
    """풀이 빌 때까지 뽑아 발문 집합을 만든다(표본이 아니라 공간 전체)."""
    seen: set[str] = set()
    while True:
        candidate = generator.generate(_SPEC)  # type: ignore[attr-defined]
        if candidate is None:
            return seen
        seen.add(candidate.problem.question_text)


@pytest.mark.parametrize("kind", ["극대", "극소"])
def test_mc_templates_share_nothing_with_short_answer_templates(kind: str) -> None:
    """템플릿 집합이 서로소 — 한 건이라도 공유하면 같은 발문이 두 형식으로 새어 나온다."""
    shared = set(calc._MC_VALUE_TEMPLATES[kind]) & set(calc._VALUE_TEMPLATES[kind])
    assert shared == set(), f"{kind} 템플릿 공유: {sorted(shared)}"


@pytest.mark.parametrize("kind", ["극대", "극소"])
def test_mc_templates_are_all_selection_prompts(kind: str) -> None:
    """객관식 발문은 전부 *선택 지시*다 — 선지가 있는데 '구하시오'로 묻는 형식 불일치 차단."""
    for template in calc._MC_VALUE_TEMPLATES[kind]:
        assert "고르시오" in template, f"선택 지시 아님: {template}"
        assert "구하시오" not in template, f"서술형 지시 혼입: {template}"


def test_question_spaces_are_disjoint_exhaustively() -> None:
    """전수 열거 — 두 생성기가 같은 발문을 낼 수 있는 조합이 하나도 없다."""
    value_questions = _drain_questions(calc.CalculusExtremumValueSkeletonGenerator())
    mc_questions = _drain_questions(calc.CalculusExtremumMCSkeletonGenerator(_MC_CODES))
    assert value_questions, "단답형 공간이 비었다 — 열거 자체가 실패했다"
    assert mc_questions, "객관식 공간이 비었다 — 열거 자체가 실패했다"
    overlap = value_questions & mc_questions
    assert overlap == set(), f"발문 공간 교집합 {len(overlap)}건: {sorted(overlap)[:3]}"


def test_skeleton_space_is_still_shared_and_that_is_recorded() -> None:
    """뼈대 공간은 **여전히 공유된다** — 이 테스트가 닫지 않은 축을 수치로 남긴다.

    발문 축이 0이라고 해서 두 생성기가 서로소인 것은 아니다. 같은 `(m, n, kind)` 뼈대가 양쪽
    풀에 있으면 같은 삼차함수가 단답형·객관식으로 각각 출제될 수 있다. 그 처분(뼈대 단위 해시
    파티션 + 코퍼스 재생성)은 승계 태스크 소관이며, 이 단언은 그 사실이 조용히 잊히지 않게
    한다 — 공유 수가 0이 되면(=승계 태스크가 착지하면) 이 테스트가 실패해 갱신을 강제한다.
    """
    value_keys = {(s.m, s.n, s.kind) for s in calc._build_value_pool()}
    mc_keys = {(s.m, s.n, s.kind) for s in calc._build_mc_pool()}
    shared = value_keys & mc_keys
    assert len(shared) == 140, (
        f"뼈대 공유 {len(shared)}쌍 — 승계 태스크가 파티션을 넣었다면 이 기대값과 "
        "위 docstring을 함께 갱신하라(0이면 축이 닫힌 것)."
    )
