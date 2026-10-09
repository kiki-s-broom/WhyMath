"""S4-55 — VerificationTier 개편 단위 테스트.

검증 축:
  ① 신규 tier 7종이 정의되어 있다.
  ② 기존 `MACHINE_EXHAUSTIVE`는 `FINITE_EXHAUSTIVE`로 alias 해석.
  ③ 기존 `MACHINE_SAMPLED`는 `NUMERIC_SAMPLING`으로 alias 해석.
  ④ `read_verification_tier()`가 alias 해석을 수행.
  ⑤ `stamp_verification_tier()`는 신규값을 그대로 기록.
  ⑥ 미지 값은 `UnknownVerificationTierError`.
  ⑦ (S4-72) 입력이 문자열이 아니라 enum 멤버여도 같은 alias 규칙을 탄다 — 레거시 멤버는
     신규 멤버로 해석되고, 신규 멤버는 자기 자신을 돌려준다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.verification_tier import (
    VERIFICATION_TIER_KEY,
    UnknownVerificationTierError,
    VerificationTier,
    read_verification_tier,
    stamp_verification_tier,
)


def test_new_tiers_are_defined() -> None:
    assert VerificationTier.FINITE_EXHAUSTIVE.value == "finite_exhaustive"
    assert VerificationTier.SYMBOLIC_PROOF.value == "symbolic_proof"
    assert VerificationTier.DETERMINISTIC_DATA.value == "deterministic_data"
    assert VerificationTier.NUMERIC_SAMPLING.value == "numeric_sampling"
    assert VerificationTier.STATISTICAL_ESTIMATE.value == "statistical_estimate"
    assert VerificationTier.RESIDUE_REVIEWED.value == "residue_reviewed"
    assert VerificationTier.HUMAN_REVIEWED.value == "human_reviewed"


def test_legacy_tiers_preserved() -> None:
    """v1 코퍼스의 문자열값이 그대로 VerificationTier 멤버로 존재해야 한다."""
    assert VerificationTier.MACHINE_EXHAUSTIVE.value == "machine_exhaustive"
    assert VerificationTier.MACHINE_SAMPLED.value == "machine_sampled"


def test_read_alias_machine_exhaustive() -> None:
    assert read_verification_tier({VERIFICATION_TIER_KEY: "machine_exhaustive"}) is (
        VerificationTier.FINITE_EXHAUSTIVE
    )


def test_read_alias_machine_sampled() -> None:
    assert read_verification_tier({VERIFICATION_TIER_KEY: "machine_sampled"}) is (
        VerificationTier.NUMERIC_SAMPLING
    )


def test_read_new_tier_directly() -> None:
    assert read_verification_tier({VERIFICATION_TIER_KEY: "finite_exhaustive"}) is (
        VerificationTier.FINITE_EXHAUSTIVE
    )
    assert read_verification_tier({VERIFICATION_TIER_KEY: "residue_reviewed"}) is (
        VerificationTier.RESIDUE_REVIEWED
    )


def test_read_missing_returns_none() -> None:
    assert read_verification_tier({}) is None


def test_read_unknown_raises() -> None:
    with pytest.raises(UnknownVerificationTierError):
        read_verification_tier({VERIFICATION_TIER_KEY: "not_a_tier"})


def test_read_enum_instance_returns_itself() -> None:
    assert read_verification_tier({VERIFICATION_TIER_KEY: VerificationTier.SYMBOLIC_PROOF}) is (
        VerificationTier.SYMBOLIC_PROOF
    )


# 레거시 멤버 → alias 대상. 신규 7종은 이 집합의 여집합이다(새 멤버가 늘면 자동 편입).
_LEGACY_TO_ALIAS = {
    VerificationTier.MACHINE_EXHAUSTIVE: VerificationTier.FINITE_EXHAUSTIVE,
    VerificationTier.MACHINE_SAMPLED: VerificationTier.NUMERIC_SAMPLING,
}
_NEW_TIERS = [t for t in VerificationTier if t not in _LEGACY_TO_ALIAS]


@pytest.mark.parametrize(("legacy", "expected"), list(_LEGACY_TO_ALIAS.items()))
def test_read_legacy_enum_member_is_aliased(
    legacy: VerificationTier, expected: VerificationTier
) -> None:
    """레거시 *멤버*를 넘겨도 문자열 입력과 같은 alias 결과를 낸다(S4-72).

    수정 전에는 `isinstance(raw, VerificationTier)` 분기가 raw를 그대로 돌려줘 멤버 경로만
    alias를 건너뛰었다(`MACHINE_SAMPLED` 입력 → `MACHINE_SAMPLED` 출력).
    """
    assert read_verification_tier({VERIFICATION_TIER_KEY: legacy}) is expected


@pytest.mark.parametrize("tier", list(VerificationTier))
def test_read_member_and_value_string_agree(tier: VerificationTier) -> None:
    """모든 멤버에서 멤버 입력의 결과 == `.value` 문자열 입력의 결과 — 두 입력 경로의 일치."""
    from_member = read_verification_tier({VERIFICATION_TIER_KEY: tier})
    from_string = read_verification_tier({VERIFICATION_TIER_KEY: tier.value})
    assert from_member is from_string


@pytest.mark.parametrize("tier", _NEW_TIERS)
def test_read_new_enum_member_returns_itself(tier: VerificationTier) -> None:
    """신규 멤버는 alias 대상이 아니므로 멤버 입력이 자기 자신을 돌려준다."""
    assert read_verification_tier({VERIFICATION_TIER_KEY: tier}) is tier


def test_new_tier_parametrization_is_not_vacuous() -> None:
    """신규 멤버 목록이 비면 위 parametrize가 0건이 되어 조용히 통과한다 — 0건을 실패로 센다."""
    assert _NEW_TIERS, "신규 등급 멤버가 하나도 없음 — parametrize가 공허하다"
    assert set(_LEGACY_TO_ALIAS) == {
        VerificationTier.MACHINE_EXHAUSTIVE,
        VerificationTier.MACHINE_SAMPLED,
    }


def test_stamp_records_new_value() -> None:
    record: dict[str, object] = {"verify": {"answer_kind": "finite_probability"}}
    stamped = stamp_verification_tier(record, VerificationTier.FINITE_EXHAUSTIVE)
    assert stamped["verify"][VERIFICATION_TIER_KEY] == "finite_exhaustive"
    # 원본 불변
    assert record["verify"].get(VERIFICATION_TIER_KEY) is None


def test_stamp_no_verify_raises() -> None:
    with pytest.raises(ValueError):
        stamp_verification_tier({}, VerificationTier.FINITE_EXHAUSTIVE)
