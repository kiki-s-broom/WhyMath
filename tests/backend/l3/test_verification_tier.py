"""S4-55 — VerificationTier 개편 단위 테스트.

검증 축:
  ① 신규 tier 7종이 정의되어 있다.
  ② 기존 `MACHINE_EXHAUSTIVE`는 `FINITE_EXHAUSTIVE`로 alias 해석.
  ③ 기존 `MACHINE_SAMPLED`는 `NUMERIC_SAMPLING`으로 alias 해석.
  ④ `read_verification_tier()`가 alias 해석을 수행.
  ⑤ `stamp_verification_tier()`는 신규값을 그대로 기록.
  ⑥ 미지 값은 `UnknownVerificationTierError`.
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


def test_stamp_records_new_value() -> None:
    record: dict[str, object] = {"verify": {"answer_kind": "finite_probability"}}
    stamped = stamp_verification_tier(record, VerificationTier.FINITE_EXHAUSTIVE)
    assert stamped["verify"][VERIFICATION_TIER_KEY] == "finite_exhaustive"
    # 원본 불변
    assert record["verify"].get(VERIFICATION_TIER_KEY) is None


def test_stamp_no_verify_raises() -> None:
    with pytest.raises(ValueError):
        stamp_verification_tier({}, VerificationTier.FINITE_EXHAUSTIVE)
