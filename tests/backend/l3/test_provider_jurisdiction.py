"""관할(jurisdiction) 정책 단위테스트 — 순수 함수·라이브 없음 (ARCH-49 ⑧).

검증 핵심(이 축이 실제로 막는 것):
  - **상한 불변식**: 어떤 관할·어떤 opt-in 조합으로도 허용 집합이 반출 허용 집합을 넘지
    않는다 → 학생 저작(`USER_GENERATED`, export=False)은 전건 배제(전수 격자).
  - **CN 기본 보수성**: 합성 프로브(`WHYMATH_GENERATED`)만 통과, 코퍼스(`INTERNAL_OWNED`)는
    opt-in 필요, opt-in은 CN에만 작용.
  - **미확인 fail-closed**: `UNKNOWN` 관할은 허용 집합이 비어 전건 차단.
  - **무변경 보장**: `US`·`DOMESTIC`은 좁히지 않아 선언 없는 결정을 막지 않는다
    (현행 Anthropic 경로 동작 불변).

픽스처 원칙(CLAUDE.md 「픽스처가 그 절을 실제로 밟는가」): 각 절마다 *그 절이 없으면
통과하는 입력*을 픽스처로 둔다 — 교집합 절에는 `USER_GENERATED`(표에는 없지만 표를
넓히면 새는 값)를, 미선언 절에는 빈 튜플을, opt-in 절에는 `INTERNAL_OWNED`를 둔다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l3.provider_jurisdiction import (
    EXPORT_PERMITTED_LICENSES,
    JURISDICTION_ALLOWED,
    JURISDICTION_GRADE_BLOCKED,
    JURISDICTION_REASONS,
    JURISDICTION_UNDECLARED,
    Jurisdiction,
    allowed_licenses_for,
    jurisdiction_judgment,
    narrows_beyond_export_gate,
    requires_declared_grades,
)
from whymath_backend.schema.enums import LicenseType


class TestExportUpperBound:
    """허용 집합은 어떤 조합으로도 반출 허용 상한을 넘지 못한다."""

    @pytest.mark.parametrize("jurisdiction", list(Jurisdiction))
    @pytest.mark.parametrize("opt_in", [False, True])
    def test_allowed_set_never_exceeds_export_permitted(
        self, jurisdiction: Jurisdiction, opt_in: bool
    ) -> None:
        """전수 격자(관할 4 × opt-in 2) — 상한 초과가 하나도 없어야 한다."""
        allowed = allowed_licenses_for(jurisdiction, allow_internal_corpus=opt_in)
        assert allowed <= EXPORT_PERMITTED_LICENSES, (
            f"{jurisdiction.value}(opt_in={opt_in})가 반출 상한을 넘었다: "
            f"{sorted(lt.value for lt in allowed - EXPORT_PERMITTED_LICENSES)}"
        )

    @pytest.mark.parametrize("jurisdiction", list(Jurisdiction))
    @pytest.mark.parametrize("opt_in", [False, True])
    def test_student_authored_never_allowed(self, jurisdiction: Jurisdiction, opt_in: bool) -> None:
        """학생 저작(USER_GENERATED)은 **어떤 관할·어떤 설정으로도** 허용되지 않는다.

        acceptance ②가 요구한 불변식의 기계 판정. 권리 모델이 `export=False`를 박아 뒀고
        (`permission_map._USER_GENERATED`), 교집합이 그것을 관할 표보다 우선시킨다.
        """
        assert LicenseType.USER_GENERATED not in allowed_licenses_for(
            jurisdiction, allow_internal_corpus=opt_in
        )

    def test_export_permitted_excludes_the_known_blocked_grades(self) -> None:
        """상한 집합 자체의 자가검증 — 반출 금지/미확인 등급이 섞이면 전체 판정이 무너진다."""
        for blocked in (
            LicenseType.USER_GENERATED,  # 학생 저작
            LicenseType.AIHUB_OPEN,  # 국외반출 금지(별도합의 필요)
            LicenseType.UNKNOWN,  # 미확인 → fail-closed
            LicenseType.RESTRICTED,  # 명시적 제한
        ):
            assert blocked not in EXPORT_PERMITTED_LICENSES
        # 공허하게 통과하지 않도록 — 상한이 비어 있지 않음을 함께 단언한다(스캔 0건 = 실패).
        assert LicenseType.WHYMATH_GENERATED in EXPORT_PERMITTED_LICENSES
        assert LicenseType.INTERNAL_OWNED in EXPORT_PERMITTED_LICENSES


class TestCnConservativeDefault:
    """CN 관할의 기본 보수성과 opt-in의 작용 범위."""

    def test_cn_default_allows_synthetic_probe_only(self) -> None:
        assert allowed_licenses_for(Jurisdiction.CN) == frozenset({LicenseType.WHYMATH_GENERATED})

    def test_cn_opt_in_adds_internal_corpus_only(self) -> None:
        assert allowed_licenses_for(Jurisdiction.CN, allow_internal_corpus=True) == frozenset(
            {LicenseType.WHYMATH_GENERATED, LicenseType.INTERNAL_OWNED}
        )

    @pytest.mark.parametrize(
        "jurisdiction", [Jurisdiction.US, Jurisdiction.DOMESTIC, Jurisdiction.UNKNOWN]
    )
    def test_opt_in_does_not_widen_other_jurisdictions(self, jurisdiction: Jurisdiction) -> None:
        """opt-in은 CN 한 곳의 결정이지 만능 스위치가 아니다."""
        assert allowed_licenses_for(
            jurisdiction, allow_internal_corpus=True
        ) == allowed_licenses_for(jurisdiction)

    def test_cn_blocks_internal_corpus_without_opt_in(self) -> None:
        judgment = jurisdiction_judgment(
            Jurisdiction.CN, [LicenseType.INTERNAL_OWNED], allow_internal_corpus=False
        )
        assert judgment.permitted is False
        assert judgment.reason == JURISDICTION_GRADE_BLOCKED
        assert judgment.blocking_licenses == (LicenseType.INTERNAL_OWNED,)

    def test_cn_permits_internal_corpus_with_opt_in(self) -> None:
        judgment = jurisdiction_judgment(
            Jurisdiction.CN, [LicenseType.INTERNAL_OWNED], allow_internal_corpus=True
        )
        assert judgment.permitted is True
        assert judgment.reason == JURISDICTION_ALLOWED

    def test_cn_blocks_mixed_batch_on_the_offending_grade(self) -> None:
        """허용 등급과 금지 등급이 섞이면 **보수적 병합** — 하나라도 막히면 차단."""
        judgment = jurisdiction_judgment(
            Jurisdiction.CN,
            [LicenseType.WHYMATH_GENERATED, LicenseType.KOGL_1],
        )
        assert judgment.permitted is False
        assert judgment.blocking_licenses == (LicenseType.KOGL_1,)

    def test_cn_reports_each_blocking_grade_once(self) -> None:
        """중복 선언은 한 번만 보고한다(로그 가독성 — 판정 자체는 동일)."""
        judgment = jurisdiction_judgment(Jurisdiction.CN, [LicenseType.KOGL_1, LicenseType.KOGL_1])
        assert judgment.blocking_licenses == (LicenseType.KOGL_1,)


class TestUnknownFailsClosed:
    """국적 미확인 관할은 아무것도 통과시키지 않는다."""

    def test_unknown_allows_nothing(self) -> None:
        assert allowed_licenses_for(Jurisdiction.UNKNOWN) == frozenset()

    @pytest.mark.parametrize(
        "licenses",
        [
            [LicenseType.WHYMATH_GENERATED],  # CN조차 허용하는 최약 등급
            [LicenseType.PUBLIC_DOMAIN],  # 퍼블릭 도메인이어도 예외 없음
            [],  # 미선언
        ],
    )
    def test_unknown_blocks_everything(self, licenses: list[LicenseType]) -> None:
        assert jurisdiction_judgment(Jurisdiction.UNKNOWN, licenses).permitted is False


class TestNarrowingAndDeclaration:
    """좁힘 여부가 *선언 요구*를 결정한다 — 기존 경로 무변경의 근거."""

    @pytest.mark.parametrize(
        ("jurisdiction", "expected"),
        [
            (Jurisdiction.DOMESTIC, False),
            (Jurisdiction.US, False),
            (Jurisdiction.CN, True),
            (Jurisdiction.UNKNOWN, True),
        ],
    )
    def test_narrows_beyond_export_gate(self, jurisdiction: Jurisdiction, expected: bool) -> None:
        assert narrows_beyond_export_gate(jurisdiction) is expected
        assert requires_declared_grades(jurisdiction) is expected

    @pytest.mark.parametrize("jurisdiction", [Jurisdiction.US, Jurisdiction.DOMESTIC])
    def test_undeclared_passes_where_nothing_narrows(self, jurisdiction: Jurisdiction) -> None:
        """좁힘이 없으면 미선언을 막지 않는다 — 1차 게이트에 위임(현행 경로 무변경)."""
        judgment = jurisdiction_judgment(jurisdiction, [])
        assert judgment.permitted is True
        assert judgment.reason == JURISDICTION_ALLOWED

    @pytest.mark.parametrize("jurisdiction", [Jurisdiction.CN, Jurisdiction.UNKNOWN])
    def test_undeclared_blocked_where_narrowing_applies(self, jurisdiction: Jurisdiction) -> None:
        """좁히는 관할에서 미선언은 fail-closed 차단 — 손조립 결정의 기본 차단막."""
        judgment = jurisdiction_judgment(jurisdiction, [])
        assert judgment.permitted is False
        assert judgment.reason == JURISDICTION_UNDECLARED
        assert judgment.blocking_licenses == ()

    def test_cn_opt_in_still_narrows(self) -> None:
        """opt-in을 켜도 CN은 여전히 상한보다 좁다 — 선언 요구가 사라지지 않는다."""
        assert narrows_beyond_export_gate(Jurisdiction.CN, allow_internal_corpus=True) is True
        assert (
            jurisdiction_judgment(Jurisdiction.CN, [], allow_internal_corpus=True).reason
            == JURISDICTION_UNDECLARED
        )


class TestNormalizationAndVocabulary:
    """어휘를 새로 만들지 않는다 — 문자열 정규화는 1차 게이트에 위임."""

    def test_accepts_string_license_values(self) -> None:
        """`RoutingDecision`은 use_enum_values=True라 값이 문자열로 올 수 있다."""
        assert jurisdiction_judgment(Jurisdiction.CN, ["WHYMATH_GENERATED"]).permitted is True

    def test_unknown_license_string_raises_not_swallowed(self) -> None:
        """미지 문자열은 조용히 UNKNOWN으로 반올림하지 않고 전파된다(침묵 실패 금지)."""
        with pytest.raises(ValueError):
            jurisdiction_judgment(Jurisdiction.CN, ["NOT_A_REAL_LICENSE"])

    def test_reason_codes_are_exhaustive(self) -> None:
        """리포트가 버킷 키를 모두 보장하기 위한 목록 — 실제 산출 사유가 전부 들어 있다."""
        produced = {
            jurisdiction_judgment(Jurisdiction.CN, [LicenseType.WHYMATH_GENERATED]).reason,
            jurisdiction_judgment(Jurisdiction.CN, [LicenseType.KOGL_1]).reason,
            jurisdiction_judgment(Jurisdiction.CN, []).reason,
        }
        assert produced == set(JURISDICTION_REASONS)
