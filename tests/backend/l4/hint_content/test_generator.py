"""graded 힌트 템플릿 생성기 — 레벨별 노출·건너뜀 사유·결정론 (S4-11 · acceptance 생성 축).

"L1=개념 이름만·L2=단계 흐름·L3=부분 시연"을 레벨마다 본문으로 확인하고, 만들면 안 되는 경우
(검증 안 된 단계·개념 없음·마지막 단계의 시연)가 **조용히 빠지지 않고 사유와 함께** 빠짐을 확인한다.
"""

from __future__ import annotations

import re
import uuid

import pytest

from whymath_backend.l4.hint_content.generator import (
    LEVEL_SOCRATIC_CATEGORY,
    SKIP_FINAL_STEP_PARTIAL,
    SKIP_NO_CONCEPT,
    SKIP_UNVERIFIED_STEP,
    ConceptRef,
    StepSource,
    generate_step_hints,
)
from whymath_backend.l4.hint_content.models import GENERATOR_VERSION, hint_id_for
from whymath_backend.l4.socratic.categories import SocraticCategory
from whymath_backend.l4.tone_filter import filter_tone

_PID = uuid.UUID("00000000-0000-0000-0000-00000000a011")
_STEPS = ("3*x**2 + 24*x", "3*x*(x + 8)", "x = 0, x = -8")
_CONCEPT = ConceptRef(concept_id="math.algebra.common-factor", name="공통인수", source="step")
_FLOW = re.compile(r"\d+\s*(?:번째\s*)?단계|첫\s*단계|마지막\s*단계")


def _source(
    order: int = 2,
    *,
    verified: bool = True,
    concept: ConceptRef | None = _CONCEPT,
    steps: tuple[str, ...] = _STEPS,
) -> StepSource:
    return StepSource(
        solution_path_id="sp-test",
        problem_id=_PID,
        step_order=order,
        step_contents=steps,
        transition_verified=verified,
        concept=concept,
    )


def _by_level(source: StepSource) -> dict[int, str]:
    return {h.level: h.content for h in generate_step_hints(source).drafts}


class TestLevelContents:
    def test_l1_names_the_concept_only(self) -> None:
        """L1 — 개념 이름이 있고, 단계 구조(흐름 표지)·단계 식은 없다."""
        l1 = _by_level(_source())[1]
        assert "「공통인수」" in l1
        assert _FLOW.search(l1) is None
        assert not any(step.replace(" ", "") in l1.replace(" ", "") for step in _STEPS)

    def test_l1_problem_primary_source_is_phrased_as_problem_concept(self) -> None:
        """문제 대표 개념으로 대신한 L1은 '이번 단계' 개념인 척하지 않는다."""
        concept = ConceptRef(concept_id="math.x", name="인수분해", source="problem_primary")
        l1 = _by_level(_source(concept=concept))[1]
        assert "이 문제는" in l1 and "이번 단계에서는" not in l1
        step_l1 = _by_level(_source())[1]
        assert "이번 단계에서는" in step_l1

    def test_l2_reveals_flow_without_computation(self) -> None:
        """L2 — 전체 단계 수·현재 위치는 말하되 어떤 단계 식도 싣지 않는다."""
        l2 = _by_level(_source())[2]
        assert "모두 3단계" in l2 and "2번째 단계" in l2 and "1단계가 더 남아" in l2
        assert not any(step.replace(" ", "") in l2.replace(" ", "") for step in _STEPS)

    def test_l2_final_step_says_it_is_last(self) -> None:
        l2 = _by_level(_source(order=3))[2]
        assert "마지막 단계" in l2

    def test_l3_demonstrates_one_verified_transition(self) -> None:
        """L3 — 직전 식과 이번 식(검증된 전이 1개)을 보이고, 최종 결과는 싣지 않는다."""
        l3 = _by_level(_source())[3]
        assert _STEPS[0] in l3 and _STEPS[1] in l3
        assert _STEPS[2] not in l3
        assert "네가 이어 가 보자" in l3

    def test_l3_first_step_shows_only_the_first_expression(self) -> None:
        l3 = _by_level(_source(order=1))[3]
        assert _STEPS[0] in l3 and _STEPS[1] not in l3

    def test_cumulative_concept_disclosure(self) -> None:
        """개념이 있으면 L2·L3도 개념을 함께 댄다(누적 척도 L1 ⊂ L2 ⊂ L3)."""
        drafts = generate_step_hints(_source()).drafts
        assert all(h.reveals.reveals_concept_names for h in drafts)
        assert all(h.reveals.revealed_concept_ids == (_CONCEPT.concept_id,) for h in drafts)

    def test_templates_pass_tone_filter(self) -> None:
        """템플릿 자체는 정서 안전 금지 패턴 0건(게이트 C가 거부할 일이 없어야 한다)."""
        for order in (1, 2, 3):
            for hint in generate_step_hints(_source(order=order)).drafts:
                _, report = filter_tone(hint.content)
                assert report.violations == [], (order, hint.level, report.violations)


class TestDeclaredReveals:
    def test_levels_declare_their_tier(self) -> None:
        drafts = {h.level: h for h in generate_step_hints(_source()).drafts}
        r1, r2, r3 = drafts[1].reveals, drafts[2].reveals, drafts[3].reveals
        assert (r1.reveals_step_flow, r1.reveals_partial_computation) == (False, False)
        assert (r2.reveals_step_flow, r2.reveals_partial_computation) == (True, False)
        assert (r3.reveals_step_flow, r3.reveals_partial_computation) == (True, True)
        assert r1.reveal_score < r2.reveal_score < r3.reveal_score

    def test_categories_come_from_existing_socratic_enum(self) -> None:
        """전달 카테고리는 기존 6종에서 고른다(신규 힌트 유형 enum 없음)."""
        drafts = generate_step_hints(_source()).drafts
        assert {h.socratic_category for h in drafts} <= set(SocraticCategory)
        assert LEVEL_SOCRATIC_CATEGORY == {
            1: SocraticCategory.PERSPECTIVE,
            2: SocraticCategory.IMPLICATION,
            3: SocraticCategory.EVIDENCE,
        }

    def test_drafts_are_unverified_until_gated(self) -> None:
        for hint in generate_step_hints(_source()).drafts:
            assert hint.verified is False and hint.gate_report == {}
            assert hint.generator_version == GENERATOR_VERSION
            assert hint.hint_id == hint_id_for("sp-test", 2, hint.level)


class TestSkips:
    def test_unverified_step_generates_nothing(self) -> None:
        """검증 안 된 전이의 단계는 레벨 전부 건너뛴다(검증 앵커 없는 힌트 금지)."""
        gen = generate_step_hints(_source(order=1, verified=False))
        assert gen.drafts == ()
        assert gen.skipped == tuple((lv, SKIP_UNVERIFIED_STEP) for lv in (1, 2, 3))

    def test_no_concept_skips_l1_only(self) -> None:
        gen = generate_step_hints(_source(concept=None))
        assert {h.level for h in gen.drafts} == {2, 3}
        assert (1, SKIP_NO_CONCEPT) in gen.skipped
        assert all(not h.reveals.reveals_concept_names for h in gen.drafts)

    def test_final_step_skips_partial_demonstration(self) -> None:
        """마지막 단계의 시연 = 전체 풀이(Level 4) — L3를 만들지 않는다."""
        gen = generate_step_hints(_source(order=3))
        assert {h.level for h in gen.drafts} == {1, 2}
        assert (3, SKIP_FINAL_STEP_PARTIAL) in gen.skipped

    @pytest.mark.parametrize("order", [0, 4])
    def test_out_of_range_step_is_an_assembly_defect(self, order: int) -> None:
        with pytest.raises(ValueError):
            generate_step_hints(_source(order=order))


def test_generation_is_deterministic() -> None:
    """같은 원천 → 같은 초안(재실행 멱등의 전제 — 헌법 R3-01)."""
    first = generate_step_hints(_source())
    second = generate_step_hints(_source())
    assert first == second
