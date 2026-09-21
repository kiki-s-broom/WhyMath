"""개념 콘텐츠 검수 승격 게이트 계약 테스트 — AI 자기승인 차단(CLAUDE.md 협상 불가).

이 게이트가 막는 상태를 **실제로 주입해** RED를 확인한다(CLAUDE.md "보호 장치를 실패 주입 없이
'보호 있음'으로 선언 금지"). 정상 입력에서 초록인 것은 보호의 증거가 아니므로, 거부 케이스마다
**성공 방향 대조군**을 함께 둔다 — 대조군이 없으면 "전부 거부"라는 과잉 수정이 통과한다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l1.concept_content.review_gate import (
    APPROVED_STATUS,
    CERTIFIED_MACHINE_REVIEWERS,
    HUMAN_REVIEWERS,
    is_known_reviewer,
    known_reviewers,
    parse_reviewed_at,
    promotion_violations,
)

_VALID_AT = "2026-09-21T00:00:00Z"


def _violations(
    *,
    code: str = "N1",
    review_status: str = APPROVED_STATUS,
    reviewed_by: str | None = "kiki",
    reviewed_at: str | None = _VALID_AT,
) -> list[str]:
    return promotion_violations(
        code=code,
        review_status=review_status,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
    )


class TestApprovedRowNeedsSignature:
    """승인 행 서명 — 누락·빈 문자열은 거부, 등재 검수자는 통과(대조군)."""

    def test_registered_human_reviewer_passes(self) -> None:
        # 대조군 — 이것이 통과하지 않으면 아래 거부들은 "전부 거부"의 부작용일 뿐이다.
        assert _violations() == []

    @pytest.mark.parametrize("handle", [None, "", "   "])
    def test_missing_signature_is_rejected(self, handle: str | None) -> None:
        violations = _violations(reviewed_by=handle)
        assert any("reviewed_by" in v for v in violations)

    def test_unregistered_reviewer_is_rejected(self) -> None:
        violations = _violations(reviewed_by="누군가")
        assert any("승격 권위 레지스트리에 없음" in v for v in violations)


class TestAiSelfApprovalIsBlocked:
    """AI 자기승인 금지 — 에이전트 핸들은 레지스트리 밖이라 거부된다."""

    @pytest.mark.parametrize(
        "handle",
        ["claude", "Claude", "gpt-5", "qwen2-math:7b", "claude2", "c1aude", "machine", "bot"],
    )
    def test_agent_handles_are_rejected(self, handle: str) -> None:
        # allowlist라 개명 우회가 통하지 않는다 — 금지 목록이었다면 claude2·c1aude가 통과한다.
        assert _violations(reviewed_by=handle) != []

    def test_certified_machine_registry_is_empty_until_demotion_battle(self) -> None:
        """강등전(S4-16) 미통과 상태의 동결 — 항목 추가는 측정 증적을 요구한다.

        이 단언이 실패한다면 누군가 기계 판정자를 등재한 것이다. 그때는 이 테스트를 고치기 전에
        강등전 검출률 측정 증적(Wilson 하한)이 있는지부터 확인한다.
        """
        assert CERTIFIED_MACHINE_REVIEWERS == ()
        assert known_reviewers() == HUMAN_REVIEWERS


class TestNonApprovedRowsAreNotGated:
    """거부·보류 라벨은 코퍼스를 건드리지 않으므로 서명을 요구하지 않는다."""

    @pytest.mark.parametrize("status", ["rejected", "ai_estimated", "deferred"])
    def test_non_approved_rows_skip_the_gate(self, status: str) -> None:
        assert _violations(review_status=status, reviewed_by=None, reviewed_at=None) == []


class TestReviewedAt:
    """검수 시각 — 파싱 가능한 ISO 8601만. 표기 차이로 정상 라벨을 거부하면 변별력이 죽는다."""

    @pytest.mark.parametrize(
        "value", ["2026-09-21T00:00:00Z", "2026-09-21T00:00:00+00:00", "2026-09-21"]
    )
    def test_iso8601_forms_are_accepted(self, value: str) -> None:
        assert parse_reviewed_at(value) is not None
        assert _violations(reviewed_at=value) == []

    @pytest.mark.parametrize("value", [None, "", "어제", "2026-13-99", "21/09/2026"])
    def test_unparseable_values_are_rejected(self, value: str | None) -> None:
        assert parse_reviewed_at(value) is None
        assert any("reviewed_at" in v for v in _violations(reviewed_at=value))


class TestReviewerNormalization:
    """대소문자·공백 표기 차이로 정상 검수자가 거부되면 안 된다(변별력 없는 게이트 방지)."""

    @pytest.mark.parametrize("handle", ["kiki", "Kiki", "KIKI", "  kiki  "])
    def test_known_reviewer_is_case_and_space_insensitive(self, handle: str) -> None:
        assert is_known_reviewer(handle)

    def test_blank_is_not_a_reviewer(self) -> None:
        assert not is_known_reviewer("   ")
        assert not is_known_reviewer(None)


class TestRowLabelIsPreserved:
    def test_row_label_prefixes_the_message(self) -> None:
        violations = promotion_violations(
            code="N9",
            review_status=APPROVED_STATUS,
            reviewed_by=None,
            reviewed_at=None,
            row_label="[행 7] ",
        )
        assert violations and all(v.startswith("[행 7] N9") for v in violations)
