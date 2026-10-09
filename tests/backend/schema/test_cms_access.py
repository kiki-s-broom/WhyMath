"""CMS 접근 정책 동결 테스트 — P3-12 (`schema/cms_access.py`).

이 파일이 막는 것:

  ① **직무 분리** — 편집자는 검수·배포를, 검수자는 편집·배포를, 배포자는 편집·검수를 못 한다.
     `CONTENT_ADMIN`만 4개 권한을 전부 가진다(겸임).
  ② **fail-closed** — 매핑에 없는 역할(`STUDENT`)·전이 이름은 권한이 0개다.
  ③ **전이표와의 맞물림** — 매핑이 "자기 자신과 일치"하는 것만으로는 부족하다. 전이표
     (`LIFECYCLE_TRANSITIONS`)의 *의미*에서 파생한 불변식을 따로 검사한다:
       · 직접 호출 가능한 전이는 전부 권한이 달려 있다(새 전이가 조용히 "아무나 가능"이 되는 것 방지)
       · 발행·폐기·은퇴로 가는 전이는 전부 `PUBLISH`를 요구한다
       · `EDIT`로 일으킬 수 있는 전이는 검토 제출 하나뿐이다(편집자가 스스로 승인 못 함)
       · 검토자·승인자를 도장 찍는 전이(`stamp`)는 `REVIEW`를 요구한다
  ④ **읽기 전용** — 요청 처리 중 권한표가 바뀔 수 없다.
"""

from __future__ import annotations

import pytest

from whymath_backend.schema.cms_access import (
    ROLE_CAPABILITIES,
    ROLLBACK_CAPABILITY,
    TRANSITION_CAPABILITY,
    CmsCapability,
    capabilities_of,
    has_capability,
    required_capability,
    roles_with,
)
from whymath_backend.schema.enums import Role
from whymath_backend.schema.version_header import TransitionAction, VersionStatus
from whymath_backend.schema.version_lifecycle import LIFECYCLE_TRANSITIONS

_V = CmsCapability.VIEW
_E = CmsCapability.EDIT
_R = CmsCapability.REVIEW
_P = CmsCapability.PUBLISH


class TestRoleCapabilities:
    def test_each_role_has_exactly_its_capabilities(self) -> None:
        assert capabilities_of(Role.CONTENT_EDITOR) == {_V, _E}
        assert capabilities_of(Role.CONTENT_REVIEWER) == {_V, _R}
        assert capabilities_of(Role.CONTENT_PUBLISHER) == {_V, _P}
        assert capabilities_of(Role.CONTENT_ADMIN) == {_V, _E, _R, _P}

    def test_student_has_no_capability(self) -> None:
        """② 학생은 매핑 키에도 없다 — 권한 0개."""
        assert Role.STUDENT not in ROLE_CAPABILITIES
        assert capabilities_of(Role.STUDENT) == frozenset()
        for capability in CmsCapability:
            assert not has_capability(Role.STUDENT, capability)

    @pytest.mark.parametrize(
        ("role", "forbidden"),
        [
            (Role.CONTENT_EDITOR, (_R, _P)),
            (Role.CONTENT_REVIEWER, (_E, _P)),
            (Role.CONTENT_PUBLISHER, (_E, _R)),
        ],
    )
    def test_separation_of_duties(self, role: Role, forbidden: tuple[CmsCapability, ...]) -> None:
        """① 한 역할이 작성·검수·배포 중 둘 이상을 가지면 직무 분리가 무너진다."""
        for capability in forbidden:
            assert not has_capability(role, capability), f"{role.value}가 {capability.value} 보유"

    def test_only_admin_holds_all_four(self) -> None:
        holders = [r for r in Role if capabilities_of(r) == set(CmsCapability)]
        assert holders == [Role.CONTENT_ADMIN]

    def test_every_cms_role_can_view(self) -> None:
        """조회는 운영 4역할 모두의 공통분모다 — 메뉴 가시성이 여기서 파생된다."""
        assert roles_with(_V) == {
            Role.CONTENT_ADMIN,
            Role.CONTENT_EDITOR,
            Role.CONTENT_REVIEWER,
            Role.CONTENT_PUBLISHER,
        }

    def test_roles_with_is_derived_from_the_single_table(self) -> None:
        assert roles_with(_E) == {Role.CONTENT_ADMIN, Role.CONTENT_EDITOR}
        assert roles_with(_R) == {Role.CONTENT_ADMIN, Role.CONTENT_REVIEWER}
        assert roles_with(_P) == {Role.CONTENT_ADMIN, Role.CONTENT_PUBLISHER}


class TestImmutability:
    """④ 요청 처리 중 한 요청의 변경이 다음 요청의 권한을 바꾸면 안 된다."""

    def test_role_table_is_read_only(self) -> None:
        with pytest.raises(TypeError):
            ROLE_CAPABILITIES[Role.STUDENT] = frozenset({_P})  # type: ignore[index]

    def test_transition_table_is_read_only(self) -> None:
        with pytest.raises(TypeError):
            TRANSITION_CAPABILITY[TransitionAction.PUBLISH] = _E  # type: ignore[index]

    def test_capability_sets_are_frozen(self) -> None:
        for caps in ROLE_CAPABILITIES.values():
            assert isinstance(caps, frozenset)


class TestTransitionMappingIsFailClosed:
    def test_unknown_action_requires_nothing_so_callers_deny(self) -> None:
        """② 어휘에 없는 전이는 `None` — 호출자는 이를 거부로 읽는다(허용이 아니다)."""
        assert required_capability("not_an_action") is None
        assert required_capability("") is None

    @pytest.mark.parametrize("action", ["supersede", "rollback", "restore"])
    def test_compound_only_actions_have_no_direct_capability(self, action: str) -> None:
        """복합 전용 전이는 단독 호출 대상이 아니다 — 권한을 달아 두면 우회 통로가 열린다."""
        assert required_capability(action) is None

    def test_rollback_operation_requires_publish(self) -> None:
        assert ROLLBACK_CAPABILITY is _P


class TestMeshesWithLifecycleTable:
    """③ 매핑을 전이표의 의미에 맞물린다 — 매핑만 보면 자기 자신과 일치할 뿐이다."""

    def test_every_direct_transition_has_a_capability(self) -> None:
        direct = {row.action for row in LIFECYCLE_TRANSITIONS if not row.compound_only}
        assert (
            direct
        ), "전이표에서 직접 호출 가능한 전이를 하나도 못 읽었다 — 스캔 0건은 통과가 아니다"
        assert direct == set(TRANSITION_CAPABILITY), (
            "전이표와 권한표가 어긋났다 — 새 전이에는 권한을 달아야 한다: "
            f"전이표만={sorted(a.value for a in direct - set(TRANSITION_CAPABILITY))} "
            f"권한표만={sorted(a.value for a in set(TRANSITION_CAPABILITY) - direct)}"
        )

    def test_compound_only_rows_are_not_mapped(self) -> None:
        compound = {row.action for row in LIFECYCLE_TRANSITIONS if row.compound_only}
        assert compound, "복합 전용 전이를 하나도 못 읽었다"
        assert not compound & set(TRANSITION_CAPABILITY)

    def test_publishing_and_retiring_transitions_require_publish(self) -> None:
        """발행본의 상태를 바꾸는 전이(→PUBLISHED/DEPRECATED/RETIRED)는 배포 권한이다."""
        publish_side = {VersionStatus.PUBLISHED, VersionStatus.DEPRECATED, VersionStatus.RETIRED}
        checked = 0
        for row in LIFECYCLE_TRANSITIONS:
            if row.compound_only or row.target not in publish_side:
                continue
            assert (
                TRANSITION_CAPABILITY[row.action] is _P
            ), f"{row.action.value}({row.source.value}→{row.target.value})가 PUBLISH를 요구하지 않는다"
            checked += 1
        assert checked >= 3, "발행측 전이를 충분히 읽지 못했다"

    def test_edit_can_only_submit_for_review(self) -> None:
        """편집자가 일으킬 수 있는 전이는 검토 제출뿐이다 — 스스로 승인·발행하면 직무 분리가 무의미하다."""
        edit_actions = {a for a, c in TRANSITION_CAPABILITY.items() if c is _E}
        assert edit_actions == {TransitionAction.SUBMIT}
        for row in LIFECYCLE_TRANSITIONS:
            if row.action in edit_actions:
                assert row.target is VersionStatus.IN_REVIEW

    def test_stamping_transitions_require_review(self) -> None:
        """검토자·승인자 도장을 찍는 전이는 검수 권한이어야 한다(`stamp` 필드가 있는 전이)."""
        stamping = [
            row for row in LIFECYCLE_TRANSITIONS if row.stamp is not None and not row.compound_only
        ]
        assert {row.stamp for row in stamping} == {"reviewed_by", "approved_by"}
        for row in stamping:
            assert TRANSITION_CAPABILITY[row.action] is _R, row.action.value

    def test_gated_transitions_are_never_edit(self) -> None:
        """검증 게이트가 붙은 간선(QA·PUBLISH)은 편집 권한으로 일으킬 수 없다."""
        for row in LIFECYCLE_TRANSITIONS:
            if row.gate is not None and not row.compound_only:
                assert TRANSITION_CAPABILITY[row.action] is not _E, row.action.value
