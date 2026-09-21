"""오개념 매칭 *품질 게이트* 단위테스트 — WH-1 1단계 슬라이스 1 `match_misconception`(§3.3).

`apply_match_quality_gate`의 두 게이트를 hermetic(DB·임베딩·LLM 0)하게 못 박는다:
  ① top-1 신뢰도 < floor(0.65) → 후보 없음(억지 매칭 금지·CLAUDE.md "확실하지 않으면 모른다").
  ② OCR confidence < ocr_threshold(0.8) → low_quality 플래그(None이면 미적용·dormant).

신뢰도 축은 `confidence`(진단 신뢰)이며 `semantic_similarity`(표면 근접도)는 floor 판정에
*쓰지 않음*을 함께 검증한다. canned `MisconceptionMatch`를 직접 조립해 매칭 알고리즘과 분리한다.

**정직 스코프**: 이건 1단계 2도구 중 첫째(match_misconception 품질 게이트)다. 둘째
verify_step의 3-state는 후속 슬라이스이며 본 테스트 범위 밖.
"""

from __future__ import annotations

import pytest

from whymath_backend.l4.misconception.catalog import CATALOG
from whymath_backend.l4.misconception.match_gate import (
    MatchGateResult,
    apply_match_quality_gate,
)
from whymath_backend.l4.misconception.models import Misconception, MisconceptionMatch

# 카탈로그에서 임의 두 개념을 빌려 canned 매치를 만든다(내용 무관 — 게이트는 confidence만 본다).
_M0: Misconception = CATALOG[0]
_M1: Misconception = CATALOG[1]


def _match(
    misconception: Misconception,
    confidence: float,
    *,
    semantic_similarity: float | None = None,
) -> MisconceptionMatch:
    return MisconceptionMatch(
        misconception=misconception,
        confidence=confidence,
        semantic_similarity=semantic_similarity,
    )


# ──────────────────────────────────────────────────────────────────────────
# 게이트 ① — top-1 신뢰도 floor(억지 매칭 금지)
# ──────────────────────────────────────────────────────────────────────────
class TestConfidenceFloorGate:
    def test_top1_above_floor_passes_unchanged(self) -> None:
        # top-1=1.0(≥0.65) → 통과·후보 그대로·no_confident_match=False.
        matches = [_match(_M0, 1.0), _match(_M1, 0.5)]
        result = apply_match_quality_gate(matches)
        assert result.matches == matches  # 순서·원소 그대로(변형 0)
        assert result.no_confident_match is False

    def test_top1_below_floor_clears_all(self) -> None:
        # top-1=0.5(<0.65) → 후보 전체 비움·no_confident_match=True(억지 매칭 금지).
        matches = [_match(_M0, 0.5), _match(_M1, 0.4)]
        result = apply_match_quality_gate(matches)
        assert result.matches == []
        assert result.no_confident_match is True

    def test_empty_input_is_no_confident_match(self) -> None:
        result = apply_match_quality_gate([])
        assert result.matches == []
        assert result.no_confident_match is True

    def test_floor_boundary_inclusive(self) -> None:
        # 정확히 floor(0.65)는 *통과*(< 비교라 0.65는 미만이 아님).
        result = apply_match_quality_gate([_match(_M0, 0.65)])
        assert result.matches != []
        assert result.no_confident_match is False

    def test_just_below_floor_clears(self) -> None:
        result = apply_match_quality_gate([_match(_M0, 0.6499)])
        assert result.matches == []
        assert result.no_confident_match is True

    def test_custom_floor_respected(self) -> None:
        # floor를 0.9로 올리면 0.8 top-1도 걸린다(파라미터화 동작).
        result = apply_match_quality_gate([_match(_M0, 0.8)], confidence_floor=0.9)
        assert result.no_confident_match is True

    def test_semantic_similarity_not_used_for_floor(self) -> None:
        # confidence는 낮고(0.5) semantic_similarity만 높은(0.99) semantic-only 후보 →
        # floor 판정은 *confidence* 기준이라 걸러진다(두 축 분리·docstring 계약).
        matches = [_match(_M0, 0.5, semantic_similarity=0.99)]
        result = apply_match_quality_gate(matches)
        assert result.matches == []
        assert result.no_confident_match is True

    def test_passed_elements_are_same_objects(self) -> None:
        # 통과분은 *같은 객체*를 그대로 싣는다(원소 변형/재생성 0).
        m0 = _match(_M0, 0.9)
        m1 = _match(_M1, 0.7)
        result = apply_match_quality_gate([m0, m1])
        assert result.matches[0] is m0
        assert result.matches[1] is m1


# ──────────────────────────────────────────────────────────────────────────
# 게이트 ② — OCR low_quality 플래그
# ──────────────────────────────────────────────────────────────────────────
class TestOcrLowQualityGate:
    def test_low_ocr_confidence_flags_but_keeps_matches(self) -> None:
        # OCR confidence 0.7(<0.8) → low_quality=True·매칭은 *유지*(게이트 ① 통과분 그대로).
        matches = [_match(_M0, 1.0)]
        result = apply_match_quality_gate(matches, ocr_confidence=0.7)
        assert result.low_quality is True
        assert result.matches == matches  # 매칭 유지(플래그만)
        assert result.no_confident_match is False

    def test_high_ocr_confidence_no_flag(self) -> None:
        result = apply_match_quality_gate([_match(_M0, 1.0)], ocr_confidence=0.95)
        assert result.low_quality is False

    def test_none_ocr_confidence_no_flag(self) -> None:
        # OCR 입력이 아님(None) → 항상 low_quality=False(dormant).
        result = apply_match_quality_gate([_match(_M0, 1.0)], ocr_confidence=None)
        assert result.low_quality is False

    def test_ocr_threshold_boundary_inclusive(self) -> None:
        # 정확히 threshold(0.8)는 플래그 *안 함*(< 비교라 0.8은 미만이 아님).
        result = apply_match_quality_gate([_match(_M0, 1.0)], ocr_confidence=0.8)
        assert result.low_quality is False

    def test_just_below_ocr_threshold_flags(self) -> None:
        result = apply_match_quality_gate([_match(_M0, 1.0)], ocr_confidence=0.7999)
        assert result.low_quality is True

    def test_custom_ocr_threshold_respected(self) -> None:
        result = apply_match_quality_gate(
            [_match(_M0, 1.0)], ocr_confidence=0.85, ocr_threshold=0.9
        )
        assert result.low_quality is True

    def test_low_ocr_and_low_confidence_independent(self) -> None:
        # 두 게이트는 독립: top-1<floor면 후보 비움(no_confident_match)·동시에 OCR<0.8이면
        # low_quality도 True(매칭은 이미 비었지만 플래그는 OCR 축으로 따로 선다).
        result = apply_match_quality_gate([_match(_M0, 0.5)], ocr_confidence=0.7)
        assert result.matches == []
        assert result.no_confident_match is True
        assert result.low_quality is True


# ──────────────────────────────────────────────────────────────────────────
# 결과 모델·결정론
# ──────────────────────────────────────────────────────────────────────────
class TestResultModel:
    def test_field_set(self) -> None:
        result = apply_match_quality_gate([_match(_M0, 1.0)])
        assert isinstance(result, MatchGateResult)
        assert set(result.model_dump().keys()) == {
            "matches",
            "no_confident_match",
            "low_quality",
            "attribution_unclear",  # MISC-28 게이트 ③
        }

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValueError):
            MatchGateResult(matches=[], no_confident_match=False, low_quality=False, x=1)  # type: ignore[call-arg]

    def test_deterministic(self) -> None:
        matches = [_match(_M0, 0.9), _match(_M1, 0.7)]
        r1 = apply_match_quality_gate(matches, ocr_confidence=0.75)
        r2 = apply_match_quality_gate(matches, ocr_confidence=0.75)
        assert r1.model_dump() == r2.model_dump()

    def test_input_sequence_not_mutated(self) -> None:
        matches = [_match(_M0, 0.5)]
        original = list(matches)
        apply_match_quality_gate(matches)
        assert matches == original  # 입력 시퀀스 불변
