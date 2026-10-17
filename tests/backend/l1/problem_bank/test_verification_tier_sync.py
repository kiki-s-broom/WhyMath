"""S4-68 ③ — L1 `_VERIFICATION_TIER_VALUES` ↔ L3 `VerificationTier` 동기 거버넌스.

L1은 L3를 import할 수 없어(import-linter) 허용 값을 문자열 집합으로 이중 관리한다. S4-55가
`VerificationTier`를 2값에서 9값으로 넓힌 뒤에도 L1 집합은 2값에 머물러, 신규 등급을 찍은 레코드가
적재 단계에서 `ProblemCorpusError`로 거부되는 드리프트가 있었다. 이 테스트는 두 집합이 **정확히
같음**을 대조한다 — 테스트는 계층 import 계약 밖이라 양쪽을 다 볼 수 있다.

부분집합 유지는 의도가 아니다: 읽는 쪽(`read_verification_tier`)이 9값을 전부 받는다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l1.problem_bank.populate import (
    _VERIFICATION_TIER_VALUES,
    ProblemCorpusError,
    _verify_meta_from_raw,
)
from whymath_backend.l3.verification_tier import VerificationTier, read_verification_tier

_ALL_TIER_VALUES = sorted(t.value for t in VerificationTier)


def test_l1_allowed_values_equal_l3_enum_values() -> None:
    """두 집합의 일치 — 한쪽만 늘면 RED다(양방향: L3에만 있는 값도, L1에만 있는 값도 잡는다)."""
    l3_values = {t.value for t in VerificationTier}
    assert _VERIFICATION_TIER_VALUES == l3_values, (
        f"L3에만 있음: {sorted(l3_values - _VERIFICATION_TIER_VALUES)} · "
        f"L1에만 있음: {sorted(_VERIFICATION_TIER_VALUES - l3_values)}"
    )


def test_tier_enum_has_nine_values() -> None:
    """전제 고정 — 비교 대상이 9값이다(enum이 비어도 일치로 통과하는 공허 방지)."""
    assert len(_ALL_TIER_VALUES) == 9


@pytest.mark.parametrize("tier_value", _ALL_TIER_VALUES)
def test_every_l3_tier_value_is_accepted_by_loader(tier_value: str) -> None:
    """L3가 읽는 모든 등급 값을 L1 로더가 받는다 — 읽는 쪽이 받는 값을 쓰는 쪽이 거부하지 않는다."""
    verify_raw = {"conditions": "x = 1", "answer_map": {"x": "1"}, "verification_tier": tier_value}
    meta = _verify_meta_from_raw(verify_raw, slug="wm-tier-sync")
    assert meta.verification_tier == tier_value
    # 읽는 쪽 대조군: L3 리더도 같은 값을 받는다(둘이 같은 어휘를 말한다).
    assert read_verification_tier(verify_raw) is not None


@pytest.mark.parametrize("bad", ["eyeballed", "MACHINE_EXHAUSTIVE", "", " finite_exhaustive"])
def test_unknown_tier_value_is_still_rejected(bad: str) -> None:
    """대조군 — 넓힌 뒤에도 미지값은 조용히 통과하지 않는다(대소문자·공백 변형 포함)."""
    verify_raw = {"conditions": "x = 1", "answer_map": {"x": "1"}, "verification_tier": bad}
    with pytest.raises(ProblemCorpusError, match="verification_tier"):
        _verify_meta_from_raw(verify_raw, slug="wm-tier-sync")
