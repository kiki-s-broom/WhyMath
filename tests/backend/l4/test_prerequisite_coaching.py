"""L4 선수 복습 코칭 결정 단위테스트 (hermetic·순수 결정·DB 불요).

L2 선수개념 추천(`PrerequisiteGap`·막힌 선수)에서 "선수 먼저 복습" 코칭(prerequisite_review)을
결정론으로 검증한다. `PrerequisiteGap`를 직접 생성해 주입(실 SQL·async 불요·순수 함수).
"""

from __future__ import annotations

import uuid

from whymath_backend.l2.concept_diagnosis import Agreement
from whymath_backend.l2.prerequisite_recommendation import PrerequisiteGap
from whymath_backend.l4.metacognitive_trigger import (
    _PROMPT,
    _RATIONALE,
    _SOCRATIC_BY_FOCUS,
    CoachingFocus,
    CoachingTrigger,
)
from whymath_backend.l4.prerequisite_coaching import recommend_prerequisite_coaching
from whymath_backend.l4.socratic.categories import SocraticCategory

# 학생 prompt에 절대 나오면 안 되는 금기 표현(CLAUDE.md 교수학 톤·우열·정답 즉시제공·부정 강화).
_FORBIDDEN_IN_PROMPT = ["빨리", "정답", "틀렸", "못"]


def _gap(
    *,
    name_ko: str | None = "일차함수",
    concept_name: str | None = "일차함수(concept)",
    weakness: float | None = 0.2,
    code: str | None = "UC.alg.afunction.linear",
    agreement: Agreement = "agree",
    depth: int = 1,
) -> PrerequisiteGap:
    """테스트용 PrerequisiteGap 1건 — name_ko/concept_name/weakness만 코칭에 관여."""
    return PrerequisiteGap(
        concept_id=uuid.uuid4(),
        concept_code=code,
        concept_name=concept_name,
        bkt_mastery=weakness,
        irt_mastery_proxy=None,
        weakness=weakness,
        agreement=agreement,
        domain=None,
        review_status=None,
        name_ko=name_ko,
        edge_strength=0.8,
        depth=depth,
    )


class TestRecommendPrerequisiteCoaching:
    def test_empty_gaps_returns_none(self) -> None:
        """막힌 선수 없음(빈 목록) → None(선수 코칭 안 함·L5가 fallback)."""
        assert recommend_prerequisite_coaching([]) is None

    def test_single_gap_focus_prerequisite_review(self) -> None:
        """막힌 선수 1개 → focus=='prerequisite_review'·CLARIFICATION·frozen 트리거."""
        trig = recommend_prerequisite_coaching([_gap(name_ko="일차함수")])
        assert isinstance(trig, CoachingTrigger)
        assert trig.focus == "prerequisite_review"
        assert trig.socratic_category == SocraticCategory.CLARIFICATION
        assert trig.rationale and trig.prompt

    def test_rationale_and_prompt_include_top_blocker_name(self) -> None:
        """rationale(교사용)·prompt(학생용) 둘 다 top blocker name_ko를 포함(구체화)."""
        trig = recommend_prerequisite_coaching([_gap(name_ko="이차방정식")])
        assert trig is not None
        assert "이차방정식" in trig.rationale
        assert "이차방정식" in trig.prompt

    def test_top_blocker_is_gaps_zero(self) -> None:
        """top blocker는 gaps[0](L2가 weakness asc 정렬) — 첫 항목 이름이 쓰인다."""
        gaps = [
            _gap(name_ko="가장약한선수", weakness=0.1),
            _gap(name_ko="덜약한선수", weakness=0.5),
        ]
        trig = recommend_prerequisite_coaching(gaps)
        assert trig is not None
        assert "가장약한선수" in trig.prompt
        assert "덜약한선수" not in trig.prompt

    def test_multiple_gaps_appends_more_count(self) -> None:
        """선수 2개 이상이면 rationale 끝에 '(다른 막힌 선수 N개 더 있음)' 부가."""
        gaps = [_gap(name_ko="A"), _gap(name_ko="B"), _gap(name_ko="C")]
        trig = recommend_prerequisite_coaching(gaps)
        assert trig is not None
        assert "다른 막힌 선수 2개 더 있음" in trig.rationale

    def test_single_gap_no_more_count(self) -> None:
        """선수 1개면 '더 있음' 부가 없음."""
        trig = recommend_prerequisite_coaching([_gap(name_ko="A")])
        assert trig is not None
        assert "더 있음" not in trig.rationale

    def test_weakness_pct_formatted(self) -> None:
        """weakness float → 백분율(약점 신호 N%)로 rationale에 표기."""
        trig = recommend_prerequisite_coaching([_gap(weakness=0.2)])
        assert trig is not None
        assert "20%" in trig.rationale

    def test_weakness_none_graceful(self) -> None:
        """weakness None(측정 부족) → '측정 부족'로 graceful 표기(예외 0)."""
        trig = recommend_prerequisite_coaching([_gap(weakness=None)])
        assert trig is not None
        assert "측정 부족" in trig.rationale

    def test_display_name_fallback_concept_name(self) -> None:
        """name_ko 없으면 concept_name으로 fallback(둘 다 안전 표시 필드)."""
        trig = recommend_prerequisite_coaching([_gap(name_ko=None, concept_name="대체개념명")])
        assert trig is not None
        assert "대체개념명" in trig.prompt

    def test_display_name_fallback_generic(self) -> None:
        """name_ko·concept_name 둘 다 없으면 '선수개념' 일반어로 fallback(예외 0)."""
        trig = recommend_prerequisite_coaching([_gap(name_ko=None, concept_name=None)])
        assert trig is not None
        assert "선수개념" in trig.prompt

    def test_prompt_tone_guard(self) -> None:
        """톤 가드 — 학생 prompt에 금기 표현(빨리·정답·틀렸·못) 부재(CLAUDE.md 교수학)."""
        trig = recommend_prerequisite_coaching([_gap(name_ko="일차함수")])
        assert trig is not None
        for forbidden in _FORBIDDEN_IN_PROMPT:
            assert forbidden not in trig.prompt, f"금기 표현 '{forbidden}' 노출"

    def test_trigger_frozen(self) -> None:
        """CoachingTrigger는 불변(frozen) — 변경 시도 시 예외."""
        trig = recommend_prerequisite_coaching([_gap()])
        assert trig is not None
        try:
            trig.focus = "advance"  # type: ignore[misc]
        except Exception as exc:  # pydantic ValidationError(frozen)
            assert "frozen" in str(exc).lower() or "instance" in str(exc).lower()
        else:  # pragma: no cover
            raise AssertionError("frozen 모델이 변경을 허용함")

    def test_deterministic(self) -> None:
        """동일 입력 → 동일 출력(순수·결정론)."""
        gaps = [_gap(name_ko="일차함수", weakness=0.2)]
        assert recommend_prerequisite_coaching(gaps) == recommend_prerequisite_coaching(gaps)


class TestCoachingFocusExhaustiveness:
    def test_dict_keys_match_coaching_focus(self) -> None:
        """_RATIONALE/_PROMPT/_SOCRATIC_BY_FOCUS 키 집합 == CoachingFocus 10종(exhaustiveness)."""
        import typing

        focuses = set(typing.get_args(CoachingFocus))
        assert "prerequisite_review" in focuses
        assert "calibration_overconfident" in focuses
        assert "calibration_underconfident" in focuses
        assert "misconception_review" in focuses  # MISC-35
        assert len(focuses) == 10
        assert set(_RATIONALE) == focuses
        assert set(_PROMPT) == focuses
        assert set(_SOCRATIC_BY_FOCUS) == focuses

    def test_prerequisite_review_socratic_is_clarification(self) -> None:
        """prerequisite_review 정적 매핑 == CLARIFICATION(기초 지향)."""
        assert _SOCRATIC_BY_FOCUS["prerequisite_review"] == SocraticCategory.CLARIFICATION
