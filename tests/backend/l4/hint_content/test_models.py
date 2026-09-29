"""Hint 엔티티 정본 — level 1~3(4 표현 불가)·reveal_score 파생·신규 힌트 유형 enum 부재 (S4-11).

acceptance 대응:
  - "Level 4는 Hint 엔티티 밖 안전망 유지(level enum 1~3)" → Pydantic·DB CHECK·서빙 응답 3층에서
    4를 표현할 수 없음을 동결한다.
  - "reveal_score(0~1)" → 범위·플래그 파생 일치·단조(L1<L2<L3)를 동결한다.
  - "신규 힌트 유형 enum 미도입(socratic_category 기존 6종)" → 모델·테이블에 유형 필드가 없고
    카테고리 좌석이 기존 `SocraticCategory` 그 자체임을 동결한다.
"""

from __future__ import annotations

import typing
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from whymath_backend.db.models.hint import Hint as HintORM
from whymath_backend.l4.hint_content.models import (
    HINT_LEVELS,
    REVEAL_TIER_COUNT,
    Hint,
    HintLevel,
    HintReveals,
    ServedHint,
    SolutionStepRef,
    compute_reveal_score,
    disclosure_tier,
    hint_id_for,
    reveal_depth_equivalent,
)
from whymath_backend.l4.hint_deferral import HintLevel as DeferralLevel
from whymath_backend.l4.socratic.categories import SocraticCategory


def _ref() -> SolutionStepRef:
    return SolutionStepRef(solution_path_id="sp-x", step_order=2, problem_id=uuid.uuid4())


def _hint(level: object, **overrides: object) -> Hint:
    payload: dict[str, object] = {
        "hint_id": "hint-sp-x-s2-l1",
        "solution_step_ref": _ref(),
        "level": level,
        "reveals": HintReveals.from_flags(
            concept_names=True, step_flow=False, partial_computation=False
        ),
        "content": "본문",
    }
    payload.update(overrides)
    return Hint.model_validate(payload)


class TestLevelFourIsNotAHint:
    def test_level_literal_is_exactly_one_to_three(self) -> None:
        """HintLevel Literal·순회 튜플 둘 다 {1,2,3} — 답 미루기 1~4와 달리 4가 없다."""
        assert set(typing.get_args(HintLevel)) == {1, 2, 3}
        assert HINT_LEVELS == (1, 2, 3)
        # 대조: 답 미루기 단계에는 4(전체 풀이)가 있다 — 두 척도가 다름을 함께 고정한다.
        assert 4 in typing.get_args(DeferralLevel)

    @pytest.mark.parametrize("bad", [0, 4, 5])
    def test_hint_rejects_level_outside_graded_scale(self, bad: int) -> None:
        with pytest.raises(ValidationError):
            _hint(bad)

    def test_served_hint_rejects_level_four(self) -> None:
        with pytest.raises(ValidationError):
            ServedHint(hint_id="h", level=4, step_order=1, content="c", reveal_score=1.0)  # type: ignore[arg-type]

    def test_db_check_constraint_bounds_level(self) -> None:
        """DB도 CHECK로 1~3을 봉인한다(Pydantic을 우회한 적재도 거부)."""
        ddl = str(CreateTable(HintORM.__table__).compile(dialect=postgresql.dialect()))
        assert "CONSTRAINT ck_hints_level_graded_1_3 CHECK (level BETWEEN 1 AND 3)" in ddl
        assert "CONSTRAINT ck_hints_reveal_score_unit" in ddl

    @pytest.mark.parametrize("level", [1, 2, 3])
    def test_graded_levels_are_accepted(self, level: int) -> None:
        assert _hint(level).level == level


class TestRevealScore:
    @pytest.mark.parametrize(
        ("flags", "tier"),
        [
            ((False, False, False), 0),
            ((True, False, False), 1),
            ((False, True, False), 2),
            ((True, True, False), 2),
            ((False, True, True), 3),
            ((True, True, True), 3),
            ((False, False, True), 3),
        ],
    )
    def test_tier_is_the_deepest_disclosure(
        self, flags: tuple[bool, bool, bool], tier: int
    ) -> None:
        concept, flow, partial = flags
        assert (
            disclosure_tier(concept_names=concept, step_flow=flow, partial_computation=partial)
            == tier
        )
        score = compute_reveal_score(
            concept_names=concept, step_flow=flow, partial_computation=partial
        )
        assert score == tier / REVEAL_TIER_COUNT
        assert 0.0 <= score <= 1.0

    def test_graded_levels_are_strictly_monotone(self) -> None:
        """L1(개념) < L2(흐름) < L3(시연) — 누적 척도의 단조성(L1 ⊂ L2 ⊂ L3)."""
        l1 = compute_reveal_score(concept_names=True, step_flow=False, partial_computation=False)
        l2 = compute_reveal_score(concept_names=True, step_flow=True, partial_computation=False)
        l3 = compute_reveal_score(concept_names=True, step_flow=True, partial_computation=True)
        assert 0.0 < l1 < l2 < l3 <= 1.0

    def test_flow_only_is_not_ranked_with_concept_only(self) -> None:
        """가중 합이었다면 '흐름만'과 '개념만'이 같은 점수가 된다 — 최고 단계 정의는 가른다."""
        flow_only = compute_reveal_score(
            concept_names=False, step_flow=True, partial_computation=False
        )
        concept_only = compute_reveal_score(
            concept_names=True, step_flow=False, partial_computation=False
        )
        assert flow_only > concept_only

    def test_score_must_match_flags(self) -> None:
        """점수는 플래그의 함수 — 자유 입력(어긋난 값)은 검증에서 거부된다."""
        with pytest.raises(ValidationError):
            HintReveals(reveals_concept_names=True, reveal_score=0.9)

    @pytest.mark.parametrize("bad", [-0.01, 1.01])
    def test_score_bounds(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            HintReveals(reveal_score=bad)

    def test_depth_equivalent_maps_to_hint_level_scale(self) -> None:
        """깊이 환산 = 3×점수 — 레벨 L의 검수 힌트는 깊이 L(KPI 2.5+와 같은 눈금)."""
        for level, flags in ((1, (True, False, False)), (2, (True, True, False))):
            score = compute_reveal_score(
                concept_names=flags[0], step_flow=flags[1], partial_computation=flags[2]
            )
            assert reveal_depth_equivalent(score) == pytest.approx(level)
        assert reveal_depth_equivalent(1.0) == pytest.approx(3.0)
        assert reveal_depth_equivalent(0.0) == 0.0


class TestNoNewHintTypeEnum:
    def test_hint_model_has_no_type_axis(self) -> None:
        """힌트 유형 필드가 없다 — 문서 6유형은 기존 3축 crosswalk로 표현한다."""
        fields = set(Hint.model_fields)
        assert not {f for f in fields if "type" in f or "kind" in f}, fields

    def test_socratic_category_seat_is_the_existing_enum(self) -> None:
        """카테고리 좌석의 타입이 기존 L4 `SocraticCategory`(6종) 그 자체다."""
        annotation = Hint.model_fields["socratic_category"].annotation
        assert set(typing.get_args(annotation)) == {SocraticCategory, type(None)}
        assert len(SocraticCategory) == 6

    def test_hints_table_has_no_type_column(self) -> None:
        columns = set(HintORM.__table__.columns.keys())
        assert not {c for c in columns if "type" in c or "kind" in c}, columns

    def test_unknown_socratic_category_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _hint(1, socratic_category="hint_formula")


def test_hint_id_is_deterministic_generation_slot() -> None:
    """생성 자리(경로·단계·레벨) = 정체성 — 재실행 멱등의 기반(헌법 R3-02 동형)."""
    assert hint_id_for("sp-1", 3, 2) == "hint-sp-1-s3-l2"
    assert hint_id_for("sp-1", 3, 2) == hint_id_for("sp-1", 3, 2)
    assert hint_id_for("sp-1", 3, 2) != hint_id_for("sp-1", 3, 3)
