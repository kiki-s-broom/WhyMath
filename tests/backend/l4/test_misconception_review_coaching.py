"""MISC-35 오개념 복습 코칭 — 순수 결정 함수 계약 동결.

`recommend_misconception_review_coaching`은 조건절 3개(빈 세트·신뢰도 바닥·카탈로그 해소)로
None을 돌려준다. 각 절마다 **그 절이 없으면 통과해 버리는 입력**을 픽스처로 둔다 — 절을 지웠을
때 GREEN이면 가드가 관대한 게 아니라 픽스처가 그 자리를 안 지나간 것이기 때문이다(CLAUDE.md
"픽스처가 그 절을 실제로 밟는가"). 각 절에는 **성공 방향 대조군**을 함께 둔다 — 대조군이 없으면
"전부 None으로 접는" 과잉 수정이 통과한다.
"""

from __future__ import annotations

import typing

import pytest

from whymath_backend.l4.metacognitive_trigger import (
    _PROMPT,
    _RATIONALE,
    _SOCRATIC_BY_FOCUS,
    CoachingFocus,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.misconception.intervene import _LOW_CONFIDENCE
from whymath_backend.l4.misconception_review_coaching import (
    _MIN_CONFIDENCE,
    recommend_misconception_review_coaching,
)
from whymath_backend.l4.socratic.categories import SocraticCategory

# 실재 카탈로그 id 2종 — 하드코딩이 아니라 *실재*임을 모듈 로드 시점에 단언한다. 카탈로그에서
# 사라지면 이 파일이 즉시 깨져야 한다(없는 id로 조용히 None을 받아 "통과"하면 안 된다).
_REAL_ID = "distribution-over-power"
_REAL_ID_2 = "sign-flip-in-inequality"
for _fixture_id in (_REAL_ID, _REAL_ID_2):
    assert _fixture_id in CATALOG_BY_ID, f"픽스처 오개념 id {_fixture_id}가 카탈로그에서 사라졌다"


def _hyp(
    misconception_id: str = _REAL_ID,
    confidence: float = 0.9,
    *,
    turns_since_evidence: int = 0,
    evidence_count: int = 1,
) -> MisconceptionHypothesis:
    return MisconceptionHypothesis(
        misconception_id=misconception_id,
        confidence=confidence,
        turns_since_evidence=turns_since_evidence,
        evidence_count=evidence_count,
    )


class TestEmptySet:
    """절 ①: `select_focus`가 None → 코칭 없음."""

    def test_empty_returns_none(self) -> None:
        assert recommend_misconception_review_coaching([]) is None

    def test_nonempty_returns_trigger(self) -> None:
        """대조군 — 절 ①이 삭제돼도 이 테스트는 통과한다(그래서 위 테스트가 필요하다)."""
        assert recommend_misconception_review_coaching([_hyp()]) is not None


class TestConfidenceFloor:
    """절 ②: 초점 신뢰도가 보류 바닥 미만이면 코칭하지 않는다(오답→오개념 단정 금지)."""

    def test_below_floor_returns_none(self) -> None:
        assert recommend_misconception_review_coaching([_hyp(confidence=0.49)]) is None

    def test_exactly_at_floor_returns_trigger(self) -> None:
        """경계 — `<` 이므로 바닥 *정확히*는 통과한다. `<=`로 바꾸면 이 테스트가 잡는다."""
        assert recommend_misconception_review_coaching([_hyp(confidence=_MIN_CONFIDENCE)]) is not None

    def test_just_above_floor_returns_trigger(self) -> None:
        assert recommend_misconception_review_coaching([_hyp(confidence=0.51)]) is not None

    def test_floor_is_the_intervene_hold_threshold(self) -> None:
        """개입 채널의 보류 바닥과 **같은 상수**여야 한다 — 복제하면 조용히 갈라진다."""
        assert _MIN_CONFIDENCE is _LOW_CONFIDENCE

    def test_floor_is_overridable(self) -> None:
        """호출자가 바닥을 올리면 같은 가설이 보류로 바뀐다(인자가 실제로 쓰인다)."""
        assert recommend_misconception_review_coaching([_hyp(confidence=0.6)]) is not None
        assert (
            recommend_misconception_review_coaching([_hyp(confidence=0.6)], min_confidence=0.7)
            is None
        )


class TestCatalogResolution:
    """절 ③: 느슨 id(카탈로그 부재)는 안전 라벨을 만들 수 없으므로 날조하지 않고 보류한다."""

    def test_unknown_id_returns_none(self) -> None:
        unknown = "no-such-misconception-id-xyz"
        assert unknown not in CATALOG_BY_ID  # 픽스처가 이 절을 실제로 밟는지 먼저 확인.
        assert recommend_misconception_review_coaching([_hyp(unknown, confidence=0.95)]) is None

    def test_known_id_returns_trigger(self) -> None:
        """대조군 — 신뢰도는 그대로 높고 id만 실재로 바꾸면 통과한다(차이가 id 하나임을 고정)."""
        assert recommend_misconception_review_coaching([_hyp(_REAL_ID, confidence=0.95)]) is not None


class TestFocusSelection:
    """초점은 *첫 원소*다 — 입력이 내림차순 정렬이라는 계약을 믿고 재정렬하지 않는다."""

    def test_uses_first_element_not_max(self) -> None:
        # 일부러 내림차순이 아닌 입력을 준다. 함수가 몰래 max()로 고르면 두 번째 이름이 나온다.
        assert _REAL_ID_2 in CATALOG_BY_ID
        trig = recommend_misconception_review_coaching(
            [_hyp(_REAL_ID, confidence=0.6), _hyp(_REAL_ID_2, confidence=0.95)]
        )
        assert trig is not None
        assert CATALOG_BY_ID[_REAL_ID].name_kr in trig.prompt
        assert CATALOG_BY_ID[_REAL_ID_2].name_kr not in trig.prompt

    def test_deterministic(self) -> None:
        """ε-탐색을 쓰지 않으므로 같은 입력은 항상 같은 출력이다(전역 random 유입 검출)."""
        hyps = [_hyp(_REAL_ID, confidence=0.9), _hyp(_REAL_ID_2, confidence=0.8)]
        first = recommend_misconception_review_coaching(hyps)
        for _ in range(20):
            assert recommend_misconception_review_coaching(hyps) == first


class TestTriggerShape:
    def test_focus_and_socratic_category(self) -> None:
        trig = recommend_misconception_review_coaching([_hyp()])
        assert trig is not None
        assert trig.focus == "misconception_review"
        assert trig.socratic_category == SocraticCategory.ASSUMPTION

    def test_display_label_is_in_both_texts(self) -> None:
        trig = recommend_misconception_review_coaching([_hyp()])
        assert trig is not None
        label = CATALOG_BY_ID[_REAL_ID].name_kr
        assert label in trig.rationale
        assert label in trig.prompt

    def test_other_suspicions_count_appended(self) -> None:
        trig = recommend_misconception_review_coaching(
            [_hyp(_REAL_ID, 0.9), _hyp(_REAL_ID_2, 0.8)]
        )
        assert trig is not None
        assert "다른 의심 1개 더 있음" in trig.rationale

    def test_single_hypothesis_has_no_count_suffix(self) -> None:
        """대조군 — 1건이면 그 문구가 없어야 한다(조건절을 지우면 '0개 더 있음'이 샌다)."""
        trig = recommend_misconception_review_coaching([_hyp()])
        assert trig is not None
        assert "다른 의심" not in trig.rationale


class TestExposureSafety:
    """CLAUDE.md 우선순위 #2 — 오개념 본문·신뢰도 수치는 학생 노출 문면에 흐르지 않는다."""

    def test_canonical_statement_not_leaked(self) -> None:
        mis = CATALOG_BY_ID[_REAL_ID]
        # 이 픽스처가 유효하려면 canonical_statement가 name_kr과 서로 달라야 한다(변별력 전제).
        assert mis.canonical_statement and mis.canonical_statement != mis.name_kr
        trig = recommend_misconception_review_coaching([_hyp()])
        assert trig is not None
        assert mis.canonical_statement not in trig.prompt
        assert mis.canonical_statement not in trig.rationale

    def test_counterexample_not_leaked(self) -> None:
        """반례는 *주지 않는다* — 학생이 스스로 수를 넣어 보게 한다(답 미루기)."""
        mis = CATALOG_BY_ID[_REAL_ID]
        trig = recommend_misconception_review_coaching([_hyp()])
        assert trig is not None
        assert mis.counterexample not in trig.prompt

    @pytest.mark.parametrize("confidence", [0.51, 0.73, 0.9, 1.0])
    def test_confidence_number_not_leaked(self, confidence: float) -> None:
        trig = recommend_misconception_review_coaching([_hyp(confidence=confidence)])
        assert trig is not None
        text = trig.prompt + trig.rationale
        for form in (str(confidence), f"{confidence:.0%}", f"{confidence:.2f}"):
            assert form not in text

    def test_rationale_marks_it_as_hypothesis_not_diagnosis(self) -> None:
        """가설은 확정 라벨이 아니다 — 교사용 근거가 그 사실을 문면에 남겨야 한다."""
        trig = recommend_misconception_review_coaching([_hyp()])
        assert trig is not None
        assert "확정 진단 아님" in trig.rationale

    def test_student_prompt_is_hypothetical_and_not_accusatory(self) -> None:
        trig = recommend_misconception_review_coaching([_hyp()])
        assert trig is not None
        assert trig.prompt.startswith("혹시")
        for banned in ("틀렸", "못 ", "오류를 범", "잘못했"):
            assert banned not in trig.prompt


class TestFocusCatalogWiring:
    """신규 포커스가 정본 카탈로그 3종에 전부 등재됐는가(exhaustiveness의 이 태스크 몫)."""

    def test_focus_registered_in_all_three_dicts(self) -> None:
        assert "misconception_review" in set(typing.get_args(CoachingFocus))
        assert "misconception_review" in _RATIONALE
        assert "misconception_review" in _PROMPT
        assert "misconception_review" in _SOCRATIC_BY_FOCUS

    def test_static_template_is_not_what_the_function_emits(self) -> None:
        """정적 템플릿은 exhaustiveness용이고, 실제 발화는 초점 라벨로 *동적 구성*된다."""
        trig = recommend_misconception_review_coaching([_hyp()])
        assert trig is not None
        assert trig.prompt != _PROMPT["misconception_review"]
        assert trig.rationale != _RATIONALE["misconception_review"]
